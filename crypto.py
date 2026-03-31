# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Crypto Module

Two layers:
  1. Ed25519  (pynacl SigningKey)  — every expense/settlement/comment is
     signed by the author (authenticity + creator integrity)
  2. SecretBox (XSalsa20-Poly1305) — all group data encrypted with a key
     derived from the group password (confidentiality between groups)

Key derivation:
  SecretBox key: Argon2id (OPSLIMIT_MODERATE / MEMLIMIT_MODERATE) from
  password + random 16-byte salt per group. The salt is shared via QR code.
  Argon2id is memory-hard and resistant to GPU/ASIC brute-force attacks.

Why pynacl / libsodium:
  - Battle-tested, audited C library (libsodium) with thin Python bindings
  - SecretBox nonce management is built-in (random 24-byte nonce prepended)
  - Argon2id is the Password Hashing Competition winner (2015)
  - Consistent API across Python, Kotlin (TweetNaCl / lazysodium), Swift

Wire format for encrypted blobs:
  SecretBox.encrypt() returns nonce (24 bytes) + ciphertext + MAC (16 bytes)
  The result is opaque — without the key neither content nor length is known.
"""

import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING, Optional

import nacl.signing
import nacl.secret
import nacl.pwhash
import nacl.utils
import nacl.encoding
import nacl.exceptions

if TYPE_CHECKING:
    from models import Expense, RecordedSettlement, Comment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def generate_private_key() -> nacl.signing.SigningKey:
    """Generates a new random Ed25519 signing key."""
    return nacl.signing.SigningKey.generate()


def private_key_to_bytes(key: nacl.signing.SigningKey) -> bytes:
    """Serializes the signing key seed (32 bytes)."""
    return bytes(key)


def private_key_from_bytes(raw: bytes) -> nacl.signing.SigningKey:
    """Restores a signing key from its 32-byte seed."""
    return nacl.signing.SigningKey(raw)


def get_public_key_hex(key: nacl.signing.SigningKey) -> str:
    """Returns the 32-byte verify key as a hex string."""
    return key.verify_key.encode(nacl.encoding.HexEncoder).decode()


# ---------------------------------------------------------------------------
# Argon2id KDF + SecretBox
# ---------------------------------------------------------------------------

def generate_group_salt() -> bytes:
    """
    Generates a cryptographically secure 16-byte salt for a new group.
    Generated once at group creation, shared via QR code with all members.
    """
    return nacl.utils.random(16)


def _group_box(group_password: str, group_salt: bytes) -> nacl.secret.SecretBox:
    """
    Derives a 32-byte key via Argon2id and returns a SecretBox.

    Argon2id advantages over PBKDF2:
      - Memory-hard: requires significant RAM, defeating GPU/ASIC attacks
      - Winner of the Password Hashing Competition (2015)
      - Same API available in libsodium (Kotlin/Swift/Rust/Go)

    OPSLIMIT_MODERATE / MEMLIMIT_MODERATE: ~64 MB RAM, ~0.1s on modern HW.
    For interactive use this is acceptable; for bulk attacks it's expensive.

    Salt must be exactly 16 bytes (nacl.pwhash.argon2id.SALTBYTES).
    """
    if len(group_salt) != nacl.pwhash.argon2id.SALTBYTES:
        raise ValueError(
            f"Salt must be {nacl.pwhash.argon2id.SALTBYTES} bytes, "
            f"got {len(group_salt)}"
        )
    key = nacl.pwhash.argon2id.kdf(
        nacl.secret.SecretBox.KEY_SIZE,
        group_password.encode("utf-8"),
        group_salt,
        opslimit=nacl.pwhash.argon2id.OPSLIMIT_MODERATE,
        memlimit=nacl.pwhash.argon2id.MEMLIMIT_MODERATE,
    )
    return nacl.secret.SecretBox(key)


def group_topic_id(group_salt: bytes) -> str:
    """
    P2P routing topic ID derived from the group salt.

    Why salt, not password:
      - Salt is random (128 bit) → topic ID cannot be guessed from password
      - Password is never exposed as a hash
      - Salt IS the group identifier; password IS the crypto key
      - Salt is shared in the QR code, it is not secret
    """
    if not group_salt:
        return "legacy-no-salt"
    return hashlib.sha256(group_salt).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Ed25519 — signing (generic helper)
# ---------------------------------------------------------------------------

def _sign(data: bytes, key: nacl.signing.SigningKey) -> str:
    """Signs data and returns the 64-byte signature as hex."""
    return key.sign(data).signature.hex()


def _verify(data: bytes, signature_hex: str, pubkey_hex: str) -> bool:
    """Verifies an Ed25519 signature. Returns False on any error."""
    try:
        vk = nacl.signing.VerifyKey(
            bytes.fromhex(pubkey_hex), encoder=nacl.encoding.RawEncoder)
        vk.verify(data, bytes.fromhex(signature_hex))
        return True
    except (nacl.exceptions.BadSignatureError, Exception) as e:
        logger.debug("Signature verification failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Expense
# ---------------------------------------------------------------------------

def sign_expense(expense: "Expense", key: nacl.signing.SigningKey) -> str:
    return _sign(expense.canonical_bytes(), key)


def verify_expense(expense: "Expense") -> bool:
    if not expense.signature:
        return False
    ok = _verify(expense.canonical_bytes(), expense.signature,
                 expense.payer_pubkey)
    if not ok:
        logger.warning("Invalid signature for expense %s", expense.id[:8])
    return ok


def encrypt_expense(expense: "Expense", group_password: str,
                    group_salt: bytes = b"") -> bytes:
    """Serializes and encrypts an expense. Returns nonce+ciphertext+MAC."""
    box  = _group_box(group_password, group_salt)
    data = json.dumps(expense.to_dict(), ensure_ascii=False).encode()
    return bytes(box.encrypt(data))


def decrypt_expense(blob: bytes, group_password: str,
                    group_salt: bytes = b"") -> Optional["Expense"]:
    """Decrypts an expense blob. Returns None on error."""
    from models import Expense
    try:
        box  = _group_box(group_password, group_salt)
        data = box.decrypt(blob)
        return Expense.from_dict(json.loads(data))
    except Exception as e:
        logger.warning("Expense decryption failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

def sign_settlement(settlement, key: nacl.signing.SigningKey) -> str:
    return _sign(settlement.canonical_bytes(), key)


def verify_settlement(settlement) -> bool:
    if not settlement.signature:
        return False
    ok = _verify(settlement.canonical_bytes(), settlement.signature,
                 settlement.from_pubkey)
    if not ok:
        logger.warning("Invalid signature for settlement %s",
                       settlement.id[:8])
    return ok


def encrypt_settlement(settlement, group_password: str,
                       group_salt: bytes = b"") -> bytes:
    box  = _group_box(group_password, group_salt)
    data = json.dumps(settlement.to_dict(), ensure_ascii=False).encode()
    return bytes(box.encrypt(data))


def decrypt_settlement(blob: bytes, group_password: str,
                       group_salt: bytes = b"") -> Optional["RecordedSettlement"]:
    from models import RecordedSettlement
    try:
        box  = _group_box(group_password, group_salt)
        data = box.decrypt(blob)
        return RecordedSettlement.from_dict(json.loads(data))
    except Exception as e:
        logger.warning("Settlement decryption failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------

def sign_comment(comment, key: nacl.signing.SigningKey) -> str:
    return _sign(comment.canonical_bytes(), key)


def verify_comment(comment) -> bool:
    if not comment.signature:
        return False
    ok = _verify(comment.canonical_bytes(), comment.signature,
                 comment.author_pubkey)
    if not ok:
        logger.warning("Invalid signature for comment %s", comment.id[:8])
    return ok


def encrypt_comment(comment, group_password: str,
                    group_salt: bytes = b"") -> bytes:
    box  = _group_box(group_password, group_salt)
    data = json.dumps(comment.to_dict(), ensure_ascii=False).encode()
    return bytes(box.encrypt(data))


def decrypt_comment(blob: bytes, group_password: str,
                    group_salt: bytes = b"") -> Optional["Comment"]:
    from models import Comment
    try:
        box  = _group_box(group_password, group_salt)
        data = box.decrypt(blob)
        return Comment.from_dict(json.loads(data))
    except Exception as e:
        logger.warning("Comment decryption failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# File attachment encryption (used in network.py for P2P transfer)
# ---------------------------------------------------------------------------

def encrypt_chunk(data: bytes, group_password: str,
                  group_salt: bytes) -> bytes:
    """Encrypts a single file chunk. Returns nonce+ciphertext+MAC."""
    return bytes(_group_box(group_password, group_salt).encrypt(data))


def decrypt_chunk(blob: bytes, group_password: str,
                  group_salt: bytes) -> bytes:
    """Decrypts a file chunk. Raises nacl.exceptions.CryptoError on failure."""
    return bytes(_group_box(group_password, group_salt).decrypt(blob))


# ---------------------------------------------------------------------------
# SHA-256 — file attachments
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
