# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Crypto Module

Zwei Ebenen:
  1. Ed25519  – jede Ausgabe wird vom Payer signiert (Authentizität)
  2. AES-256-GCM – alle Ausgaben einer Gruppe werden mit dem
     Gruppenpasswort verschlüsselt (Vertraulichkeit zwischen Gruppen)

Ablauf beim Speichern einer Ausgabe:
  expense  →  canonical JSON  →  Ed25519-Signatur
  expense.to_dict()  →  AES-GCM(group_key)  →  verschlüsselter Blob in DB

Ablauf beim Laden:
  verschlüsselter Blob  →  AES-GCM-Entschlüsselung  →  Expense.from_dict()
  →  verify_expense()  →  anzeigen

SHA-256 für Dateianhänge: Hash wird in der Expense-Signatur eingeschlossen,
damit niemand den Anhang unbemerkt austauschen kann.
"""

import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING, Optional

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from models import Expense, Attachment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def generate_private_key() -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.generate()


def private_key_to_bytes(key: ed25519.Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def private_key_from_bytes(raw: bytes) -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw)


def get_public_key_hex(key: ed25519.Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


# ---------------------------------------------------------------------------
# Ed25519 – Ausgaben signieren
# ---------------------------------------------------------------------------

def sign_expense(expense: "Expense", private_key: ed25519.Ed25519PrivateKey) -> str:
    """Signiert canonical_bytes() der Ausgabe, gibt Hex-Signatur zurück."""
    sig = private_key.sign(expense.canonical_bytes())
    return sig.hex()


def verify_expense(expense: "Expense") -> bool:
    """Prüft die Ed25519-Signatur. False wenn fehlt oder ungültig."""
    if not expense.signature:
        return False
    try:
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(expense.payer_pubkey)
        )
        pub_key.verify(bytes.fromhex(expense.signature), expense.canonical_bytes())
        return True
    except Exception as e:
        logger.warning("Ungültige Signatur für Ausgabe %s: %s", expense.id[:8], e)
        return False


# ---------------------------------------------------------------------------
# AES-256-GCM – Gruppenverschlüsselung
# ---------------------------------------------------------------------------

def _group_aes_key(group_password: str) -> bytes:
    """Leitet einen 32-Byte AES-Schlüssel aus dem Gruppenpasswort ab."""
    return hashlib.sha256(group_password.encode("utf-8")).digest()


def group_topic_id(group_password: str) -> str:
    """Kurze Topic-ID für P2P-Routing (nicht umkehrbar)."""
    return hashlib.sha256(group_password.encode()).hexdigest()[:16]


def encrypt_expense(expense: "Expense", group_password: str) -> bytes:
    """
    Serialisiert und verschlüsselt eine Ausgabe mit dem Gruppenkey.

    Rückgabe: nonce (12 Bytes) || ciphertext (variable Länge)
    Das Ergebnis ist ein undurchsichtiger Blob — ohne das Passwort
    sind weder Beschreibung, Betrag noch Beteiligte erkennbar.
    """
    key  = _group_aes_key(group_password)
    aes  = AESGCM(key)
    data = json.dumps(expense.to_dict(), ensure_ascii=False).encode()
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_expense(blob: bytes, group_password: str) -> Optional["Expense"]:
    """
    Entschlüsselt einen Blob und gibt eine Expense zurück.
    Gibt None zurück wenn das Passwort falsch ist oder der Blob korrupt ist.
    """
    from models import Expense
    if len(blob) < 28:   # 12 nonce + mindestens 16 GCM-Tag
        return None
    try:
        key   = _group_aes_key(group_password)
        aes   = AESGCM(key)
        nonce = blob[:12]
        ct    = blob[12:]
        data  = aes.decrypt(nonce, ct, None)
        return Expense.from_dict(json.loads(data))
    except Exception as e:
        logger.warning("Entschlüsselung fehlgeschlagen: %s", e)
        return None


# ---------------------------------------------------------------------------
# SHA-256 – Dateianhänge
# ---------------------------------------------------------------------------

def hash_file(file_path: str) -> str:
    """SHA-256 Hex-Digest einer Datei (chunk-weise, RAM-schonend)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mime_type_from_path(path: str) -> str:
    """Einfache MIME-Typ-Erkennung anhand der Dateiendung."""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".pdf":  "application/pdf",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".gif":  "image/gif",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------
# Settlement-Krypto (analog zu Expense)
# ---------------------------------------------------------------------------

def sign_settlement(settlement, private_key: ed25519.Ed25519PrivateKey) -> str:
    """Signiert canonical_bytes() der Zahlung."""
    return private_key.sign(settlement.canonical_bytes()).hex()


def verify_settlement(settlement) -> bool:
    """Prüft die Ed25519-Signatur der Zahlung."""
    if not settlement.signature:
        return False
    try:
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(settlement.from_pubkey)
        )
        pub_key.verify(bytes.fromhex(settlement.signature), settlement.canonical_bytes())
        return True
    except Exception as e:
        logger.warning("Ungültige Signatur für Settlement %s: %s", settlement.id[:8], e)
        return False


def encrypt_settlement(settlement, group_password: str) -> bytes:
    """Serialisiert und verschlüsselt eine Zahlung."""
    key   = _group_aes_key(group_password)
    aes   = AESGCM(key)
    data  = json.dumps(settlement.to_dict(), ensure_ascii=False).encode()
    nonce = os.urandom(12)
    return nonce + aes.encrypt(nonce, data, None)


def decrypt_settlement(blob: bytes, group_password: str):
    """Entschlüsselt einen Settlement-Blob. None bei Fehler."""
    from models import RecordedSettlement
    if len(blob) < 28:
        return None
    try:
        key  = _group_aes_key(group_password)
        aes  = AESGCM(key)
        data = aes.decrypt(blob[:12], blob[12:], None)
        return RecordedSettlement.from_dict(json.loads(data))
    except Exception as e:
        logger.warning("Settlement-Entschlüsselung fehlgeschlagen: %s", e)
        return None
