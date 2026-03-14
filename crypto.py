# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Cryptographic Operations Module

Handles all cryptographic primitives:
- Ed25519 key generation, signing, verification
- AES-256-GCM symmetric group encryption
- SHA-256 file hashing
"""

import hashlib
import json
import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def generate_private_key() -> ed25519.Ed25519PrivateKey:
    """Generate a new Ed25519 private key."""
    return ed25519.Ed25519PrivateKey.generate()


def private_key_to_bytes(key: ed25519.Ed25519PrivateKey) -> bytes:
    """Serialize a private key to raw bytes (for storage)."""
    return key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def private_key_from_bytes(raw: bytes) -> ed25519.Ed25519PrivateKey:
    """Deserialize a private key from raw bytes."""
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw)


def get_public_key_bytes(private_key: ed25519.Ed25519PrivateKey) -> bytes:
    """Extract the public key as raw bytes."""
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


# ---------------------------------------------------------------------------
# Signing & verification
# ---------------------------------------------------------------------------

def sign(private_key: ed25519.Ed25519PrivateKey, data: bytes) -> bytes:
    """Sign data with Ed25519 private key."""
    return private_key.sign(data)


def verify(public_key_bytes: bytes, signature: bytes, data: bytes) -> bool:
    """
    Verify an Ed25519 signature.

    Returns:
        True if valid, False otherwise (never raises).
    """
    try:
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
        pub_key.verify(signature, data)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------

def hash_file(file_path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def group_key_from_password(password: str) -> bytes:
    """Derive a 32-byte AES key from a group password via SHA-256."""
    return hashlib.sha256(password.encode()).digest()


def topic_id_from_password(password: str) -> str:
    """Derive a short topic identifier from the group password."""
    return hashlib.sha256(password.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Group crypto (AES-GCM + Ed25519)
# ---------------------------------------------------------------------------

class GroupCrypto:
    """
    Combines AES-256-GCM group encryption with Ed25519 message signing.

    Every outgoing message is:
      1. Serialised to JSON
      2. Encrypted with the shared group key (AES-GCM, random nonce)
      3. Signed over (nonce || ciphertext) with the sender's private key

    This ensures:
      - Confidentiality  : only group members with the shared key can read
      - Integrity        : tampering is detected by the AES-GCM tag
      - Authenticity     : each message is tied to a specific member key
    """

    def __init__(
        self,
        group_secret_key: bytes,
        private_key: ed25519.Ed25519PrivateKey,
    ):
        if len(group_secret_key) != 32:
            raise ValueError("group_secret_key must be exactly 32 bytes")
        self.aes = AESGCM(group_secret_key)
        self.private_key = private_key
        self.public_key_bytes = get_public_key_bytes(private_key)

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def encrypt_and_sign(self, inner_data: dict) -> dict:
        """
        Encrypt and sign a payload dict.

        Args:
            inner_data: Plaintext dict (must be JSON-serialisable).

        Returns:
            Packet dict with hex-encoded fields ready for transmission.
        """
        inner_json = json.dumps(inner_data, ensure_ascii=False).encode()
        nonce = os.urandom(12)
        encrypted_data = self.aes.encrypt(nonce, inner_json, None)

        payload_to_sign = nonce + encrypted_data
        signature = self.private_key.sign(payload_to_sign)

        logger.debug("Encrypted and signed payload (%d bytes)", len(inner_json))
        return {
            "creator_pubkey": self.public_key_bytes.hex(),
            "nonce": nonce.hex(),
            "encrypted_payload": encrypted_data.hex(),
            "signature": signature.hex(),
        }

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def verify_packet(self, packet: dict) -> bool:
        """Verify the Ed25519 signature of an incoming packet."""
        try:
            nonce = bytes.fromhex(packet["nonce"])
            encrypted = bytes.fromhex(packet["encrypted_payload"])
            signature = bytes.fromhex(packet["signature"])
            pub_key_bytes = bytes.fromhex(packet["creator_pubkey"])
            return verify(pub_key_bytes, signature, nonce + encrypted)
        except Exception as e:
            logger.warning("Signature verification failed: %s", e)
            return False

    def decrypt(self, packet: dict) -> Optional[dict]:
        """
        Decrypt an incoming packet.

        Returns:
            Inner data dict, or None if decryption fails.
        """
        try:
            nonce = bytes.fromhex(packet["nonce"])
            encrypted = bytes.fromhex(packet["encrypted_payload"])
            inner_json = self.aes.decrypt(nonce, encrypted, None)
            return json.loads(inner_json)
        except Exception as e:
            logger.warning("Decryption failed: %s", e)
            return None
