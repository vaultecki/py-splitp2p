# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Crypto Module

Two layers:
  1. Ed25519  (pynacl SigningKey)  — every record signed by its author
  2. SecretBox (XSalsa20-Poly1305) — 32-byte group key encrypts wire data

Signing:
  Each model has canonical_bytes() — a deterministic byte representation
  of its synced fields (local-only fields like is_stored are excluded).
  The signature is stored in the model's `signature` field.

Encryption:
  Records are serialized via model.to_wire_dict(), JSON-encoded, then
  encrypted with SecretBox before transmission. The receiver decrypts,
  verifies the Ed25519 signature, then saves to the normalized DB.

File chunks:
  Attachment files are transferred in encrypted chunks over a direct
  libp2p stream. Each chunk is individually encrypted with SecretBox.
"""

import hashlib
import json
import logging
import os
from typing import Optional

import nacl.signing
import nacl.secret
import nacl.utils
import nacl.encoding
import nacl.exceptions

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Group key
# ---------------------------------------------------------------------------

def generate_group_key() -> bytes:
    """Random 32-byte SecretBox key. Generated once, shared via QR."""
    return nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)


def _box(group_key: bytes) -> nacl.secret.SecretBox:
    if len(group_key) != nacl.secret.SecretBox.KEY_SIZE:
        raise ValueError(
            f"Group key must be {nacl.secret.SecretBox.KEY_SIZE} bytes, "
            f"got {len(group_key)}")
    return nacl.secret.SecretBox(group_key)


# ---------------------------------------------------------------------------
# Ed25519 key management
# ---------------------------------------------------------------------------

def generate_private_key() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()

def private_key_to_bytes(key: nacl.signing.SigningKey) -> bytes:
    return bytes(key)

def private_key_from_bytes(raw: bytes) -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey(raw)

def get_public_key_hex(key: nacl.signing.SigningKey) -> str:
    return key.verify_key.encode(nacl.encoding.HexEncoder).decode()


# ---------------------------------------------------------------------------
# Sign / verify — generic
# ---------------------------------------------------------------------------

def _sign(data: bytes, key: nacl.signing.SigningKey) -> str:
    """Returns 64-byte Ed25519 signature as hex string."""
    return key.sign(data).signature.hex()


def _verify(data: bytes, sig_hex: str, pubkey_hex: str) -> bool:
    """Returns False on any error (bad sig, bad hex, wrong key)."""
    try:
        vk = nacl.signing.VerifyKey(bytes.fromhex(pubkey_hex),
                                     encoder=nacl.encoding.RawEncoder)
        vk.verify(data, bytes.fromhex(sig_hex))
        return True
    except Exception as e:
        logger.debug("Signature verification failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Record sign / verify
# Each model has canonical_bytes() which excludes local-only fields.
# ---------------------------------------------------------------------------

def sign_record(record, key: nacl.signing.SigningKey) -> str:
    """Generic: sign any model that has canonical_bytes()."""
    return _sign(record.canonical_bytes(), key)


def verify_record(record, pubkey_hex: str) -> bool:
    """Generic: verify signature on any model with canonical_bytes()."""
    if not record.signature:
        logger.warning("Missing signature on %s", type(record).__name__)
        return False
    ok = _verify(record.canonical_bytes(), record.signature, pubkey_hex)
    if not ok:
        logger.warning("Invalid signature on %s %s",
                       type(record).__name__, getattr(record, "id", "")[:8])
    return ok


# Convenience aliases for backward compat and clarity
def sign_expense(expense, key):    return sign_record(expense, key)
def sign_settlement(s, key):       return sign_record(s, key)
def sign_comment(c, key):          return sign_record(c, key)
def sign_split(s, key):            return sign_record(s, key)
def sign_attachment(a, key):       return sign_record(a, key)
def sign_user(u, key):             return sign_record(u, key)

def verify_expense(expense):
    return verify_record(expense, expense.author_pubkey)

def verify_settlement(s):
    return verify_record(s, s.author_pubkey)

def verify_comment(c):
    return verify_record(c, c.author_pubkey)

def verify_split(s):
    return verify_record(s, s.author_pubkey)

def verify_attachment(a):
    return verify_record(a, a.author_pubkey)

def verify_user(u):
    return verify_record(u, u.public_key)


# ---------------------------------------------------------------------------
# Wire encryption / decryption
# Records are encrypted for transport only — DB stores plain fields.
# ---------------------------------------------------------------------------

def encrypt_record(record, group_key: bytes) -> bytes:
    """
    Serializes record.to_wire_dict() to JSON and encrypts with SecretBox.
    Returns nonce(24) + ciphertext + MAC(16).
    """
    data = json.dumps(record.to_wire_dict(), ensure_ascii=False).encode()
    return bytes(_box(group_key).encrypt(data))


def decrypt_record(blob: bytes, group_key: bytes,
                   record_type) -> Optional[object]:
    """
    Decrypts a wire blob and reconstructs the record via from_wire_dict().
    Returns None on any error (wrong key, tampered data, missing fields).
    record_type must have a from_wire_dict() classmethod.
    """
    try:
        data = _box(group_key).decrypt(blob)
        return record_type.from_wire_dict(json.loads(data))
    except Exception as e:
        logger.warning("decrypt_record(%s) failed: %s",
                       record_type.__name__, e)
        return None


# ---------------------------------------------------------------------------
# File attachment chunk encryption
# ---------------------------------------------------------------------------

def encrypt_chunk(data: bytes, group_key: bytes) -> bytes:
    """Encrypts one file chunk. Returns nonce(24)+ciphertext+MAC(16)."""
    return bytes(_box(group_key).encrypt(data))


def decrypt_chunk(blob: bytes, group_key: bytes) -> bytes:
    """Decrypts one file chunk. Raises on failure."""
    return bytes(_box(group_key).decrypt(blob))


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------

def hash_file(file_path: str) -> str:
    """SHA-256 hex digest of a file (chunked for large files)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mime_type_from_path(path: str) -> str:
    return {
        ".pdf":  "application/pdf",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".gif":  "image/gif",
        ".webp": "image/webp",
    }.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
