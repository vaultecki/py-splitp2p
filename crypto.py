# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Crypto Module

Two layers:
  1. Ed25519  (pynacl SigningKey)  — every record signed by author
  2. SecretBox (XSalsa20-Poly1305) — random 32-byte group key, no KDF

Key model:
  Each group has a random 32-byte SecretBox key. No password, no KDF.
  The key is shared via QR code. SecretBox(key) is one line in any
  libsodium binding (pynacl, lazysodium, swift-sodium, sodiumoxide).
"""

import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING, Optional

import nacl.signing
import nacl.secret
import nacl.utils
import nacl.encoding
import nacl.exceptions

if TYPE_CHECKING:
    from models import Expense, RecordedSettlement, Comment

logger = logging.getLogger(__name__)


def generate_group_key() -> bytes:
    """Random 32-byte SecretBox key. Generated once, shared via QR."""
    return nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)




def _box(group_key: bytes) -> nacl.secret.SecretBox:
    if len(group_key) != nacl.secret.SecretBox.KEY_SIZE:
        raise ValueError(f"Group key must be {nacl.secret.SecretBox.KEY_SIZE} bytes")
    return nacl.secret.SecretBox(group_key)


def generate_private_key() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()

def private_key_to_bytes(key: nacl.signing.SigningKey) -> bytes:
    return bytes(key)

def private_key_from_bytes(raw: bytes) -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey(raw)

def get_public_key_hex(key: nacl.signing.SigningKey) -> str:
    return key.verify_key.encode(nacl.encoding.HexEncoder).decode()


def _sign(data: bytes, key: nacl.signing.SigningKey) -> str:
    return key.sign(data).signature.hex()

def _verify(data: bytes, sig_hex: str, pubkey_hex: str) -> bool:
    try:
        vk = nacl.signing.VerifyKey(bytes.fromhex(pubkey_hex),
                                     encoder=nacl.encoding.RawEncoder)
        vk.verify(data, bytes.fromhex(sig_hex))
        return True
    except Exception as e:
        logger.debug("Signature verification failed: %s", e)
        return False


def sign_expense(expense, key): return _sign(expense.canonical_bytes(), key)
def verify_expense(expense):
    ok = bool(expense.signature) and _verify(
        expense.canonical_bytes(), expense.signature, expense.payer_pubkey)
    if not ok: logger.warning("Invalid signature for expense %s", expense.id[:8])
    return ok
def encrypt_expense(expense, group_key: bytes) -> bytes:
    return bytes(_box(group_key).encrypt(
        json.dumps(expense.to_dict(), ensure_ascii=False).encode()))
def decrypt_expense(blob: bytes, group_key: bytes) -> Optional["Expense"]:
    from models import Expense
    try: return Expense.from_dict(json.loads(_box(group_key).decrypt(blob)))
    except Exception as e:
        logger.warning("Expense decryption failed: %s", e); return None


def sign_settlement(s, key): return _sign(s.canonical_bytes(), key)
def verify_settlement(s):
    ok = bool(s.signature) and _verify(
        s.canonical_bytes(), s.signature, s.from_pubkey)
    if not ok: logger.warning("Invalid signature for settlement %s", s.id[:8])
    return ok
def encrypt_settlement(s, group_key: bytes) -> bytes:
    return bytes(_box(group_key).encrypt(
        json.dumps(s.to_dict(), ensure_ascii=False).encode()))
def decrypt_settlement(blob: bytes, group_key: bytes) -> Optional["RecordedSettlement"]:
    from models import RecordedSettlement
    try: return RecordedSettlement.from_dict(json.loads(_box(group_key).decrypt(blob)))
    except Exception as e:
        logger.warning("Settlement decryption failed: %s", e); return None


def sign_comment(c, key): return _sign(c.canonical_bytes(), key)
def verify_comment(c):
    ok = bool(c.signature) and _verify(
        c.canonical_bytes(), c.signature, c.author_pubkey)
    if not ok: logger.warning("Invalid signature for comment %s", c.id[:8])
    return ok
def encrypt_comment(c, group_key: bytes) -> bytes:
    return bytes(_box(group_key).encrypt(
        json.dumps(c.to_dict(), ensure_ascii=False).encode()))
def decrypt_comment(blob: bytes, group_key: bytes) -> Optional["Comment"]:
    from models import Comment
    try: return Comment.from_dict(json.loads(_box(group_key).decrypt(blob)))
    except Exception as e:
        logger.warning("Comment decryption failed: %s", e); return None


def encrypt_chunk(data: bytes, group_key: bytes) -> bytes:
    return bytes(_box(group_key).encrypt(data))
def decrypt_chunk(blob: bytes, group_key: bytes) -> bytes:
    return bytes(_box(group_key).decrypt(blob))


def hash_file(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192): h.update(chunk)
    return h.hexdigest()

def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def mime_type_from_path(path: str) -> str:
    return {".pdf":"application/pdf",".jpg":"image/jpeg",".jpeg":"image/jpeg",
            ".png":"image/png",".gif":"image/gif",".webp":"image/webp"
            }.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
