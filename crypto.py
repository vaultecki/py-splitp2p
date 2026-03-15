# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Crypto Module

Two layers:
  1. Ed25519     - every expense is signed by the payer (authenticity)
  2. AES-256-GCM - all group expenses are encrypted with the
     group password (confidentiality between groups)

Key derivation:
  AES key: PBKDF2-HMAC-SHA256 (600,000 iterations, random 16-byte salt
           per group). Salt is generated when the group is created and
           shared with all members via QR code.
           Much more expensive than raw SHA256, prevents rainbow-table attacks.
  Topic ID: SHA256(salt)[:16] - no PBKDF2 needed, routing identifier only,
            not a cryptographic secret.

Saving an expense:
  expense -> canonical JSON -> Ed25519 signature
  expense.to_dict() -> AES-GCM(pbkdf2_key) -> encrypted blob in DB

Loading an expense:
  encrypted blob -> AES-GCM decryption -> Expense.from_dict()
  -> verify_expense() -> display

SHA-256 for attachments: hash is included in the expense signature
so nobody can silently swap the attachment.
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
    """Signs canonical_bytes() of the expense, returns hex signature."""
    sig = private_key.sign(expense.canonical_bytes())
    return sig.hex()


def verify_expense(expense: "Expense") -> bool:
    """Verifies the Ed25519 signature. Returns False if missing or invalid."""
    if not expense.signature:
        return False
    try:
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(expense.payer_pubkey)
        )
        pub_key.verify(bytes.fromhex(expense.signature), expense.canonical_bytes())
        return True
    except Exception as e:
        logger.warning("Invalid signature for expense %s: %s", expense.id[:8], e)
        return False


# ---------------------------------------------------------------------------
# AES-256-GCM - group encryption
# ---------------------------------------------------------------------------

# PBKDF2 iterations: 600,000 is the OWASP minimum recommendation (2024)
# for PBKDF2-HMAC-SHA256. ~0.2s on modern hardware -
# acceptable at app startup, expensive for brute-force attacks.
_PBKDF2_ITERATIONS = 600_000


def generate_group_salt() -> bytes:
    """
    Generates a cryptographically secure 16-byte salt for a new group.
    Generated once when the group is created and distributed to all
    members via QR code.
    """
    return os.urandom(16)


def _group_aes_key(group_password: str, group_salt: bytes) -> bytes:
    """
    Derives a 32-byte AES key via PBKDF2-HMAC-SHA256.

    group_salt: random 16-byte salt, generated once per group
                and shared via QR code. Prevents rainbow-table attacks
                and strengthens isolation between groups.

    Why PBKDF2 over Scrypt:
      PBKDF2 is available in Python stdlib (hashlib); Scrypt requires
      OpenSSL >= 1.1. Both are sufficient for this use case.
    """
    return hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=group_password.encode("utf-8"),
        salt=group_salt,
        iterations=_PBKDF2_ITERATIONS,
        dklen=32,
    )


def group_topic_id(group_salt: bytes) -> str:
    """
    Topic ID for P2P routing, derived from the group salt.

    Why salt instead of password:
      - Salt is random (128 bit) -> topic ID cannot be guessed from password.
      - Password is never exposed as a hash anywhere.
      - Salt IS the group identifier; password IS the crypto key.
      - Salt is shared in the QR code, it is not a secret.
    """
    if not group_salt:
        return "legacy-no-salt"  # backward compatibility for groups without salt
    return hashlib.sha256(group_salt).hexdigest()[:16]


def encrypt_expense(expense: "Expense", group_password: str,
                    group_salt: bytes = b"") -> bytes:
    """
    Serializes and encrypts an expense with the group key.

    Returns: nonce (12 bytes) || ciphertext (variable length)
    The result is an opaque blob - without the password
    description, amount and participants are not recoverable.
    """
    key  = _group_aes_key(group_password, group_salt)
    aes  = AESGCM(key)
    data = json.dumps(expense.to_dict(), ensure_ascii=False).encode()
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_expense(blob: bytes, group_password: str,
                    group_salt: bytes = b"") -> Optional["Expense"]:
    """
    Decrypts a blob and returns an Expense.
    Returns None if the password is wrong or the blob is corrupt.
    """
    from models import Expense
    if len(blob) < 28:   # 12 nonce + mindestens 16 GCM-Tag
        return None
    try:
        key   = _group_aes_key(group_password, group_salt)
        aes   = AESGCM(key)
        nonce = blob[:12]
        ct    = blob[12:]
        data  = aes.decrypt(nonce, ct, None)
        return Expense.from_dict(json.loads(data))
    except Exception as e:
        logger.warning("Decryption failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# SHA-256 - file attachments
# ---------------------------------------------------------------------------

def hash_file(file_path: str) -> str:
    """SHA-256 hex digest of a file (chunked, memory-efficient)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mime_type_from_path(path: str) -> str:
    """Simple MIME type detection by file extension."""
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
    """Signs canonical_bytes() of the settlement."""
    return private_key.sign(settlement.canonical_bytes()).hex()


def verify_settlement(settlement) -> bool:
    """Verifies the Ed25519 signature of the settlement."""
    if not settlement.signature:
        return False
    try:
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(settlement.from_pubkey)
        )
        pub_key.verify(bytes.fromhex(settlement.signature), settlement.canonical_bytes())
        return True
    except Exception as e:
        logger.warning("Invalid signature for settlement %s: %s", settlement.id[:8], e)
        return False


def encrypt_settlement(settlement, group_password: str,
                       group_salt: bytes = b"") -> bytes:
    """Serializes and encrypts a settlement."""
    key   = _group_aes_key(group_password, group_salt)
    aes   = AESGCM(key)
    data  = json.dumps(settlement.to_dict(), ensure_ascii=False).encode()
    nonce = os.urandom(12)
    return nonce + aes.encrypt(nonce, data, None)


def decrypt_settlement(blob: bytes, group_password: str,
                       group_salt: bytes = b"") -> Optional["RecordedSettlement"]:
    """Decrypts a settlement blob. Returns None on error."""
    from models import RecordedSettlement
    if len(blob) < 28:
        return None
    try:
        key  = _group_aes_key(group_password, group_salt)
        aes  = AESGCM(key)
        data = aes.decrypt(blob[:12], blob[12:], None)
        return RecordedSettlement.from_dict(json.loads(data))
    except Exception as e:
        logger.warning("Settlement decryption failed: %s", e)
        return None
