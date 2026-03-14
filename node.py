# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
P2P Group Node Module

High-level API that ties together cryptography and storage.
A single P2PGroupNode represents one member of a group chat:
it can compose outgoing messages and process incoming ones.
"""

import logging
import os
import time
import uuid
from typing import Optional

from crypto import (
    GroupCrypto,
    generate_private_key,
    group_key_from_password,
    hash_file,
    private_key_from_bytes,
    private_key_to_bytes,
)
from storage import merge_message

logger = logging.getLogger(__name__)


class P2PGroupNode:
    """
    Represents a single participant in a P2P group chat.

    Responsibilities:
    - Composing outgoing messages (encrypt + sign)
    - Processing incoming messages (verify + decrypt + CRDT-merge)
    - Exposing own public key for identification
    """

    def __init__(
        self,
        group_password: str,
        private_key=None,
    ):
        """
        Args:
            group_password: Shared secret that all group members know.
            private_key:    Ed25519 private key object. A new one is
                            generated if None is passed.
        """
        group_secret_key = group_key_from_password(group_password)
        if private_key is None:
            private_key = generate_private_key()
            logger.info("Generated new identity key pair")

        self.crypto = GroupCrypto(group_secret_key, private_key)
        logger.info(
            "Node initialised, pubkey prefix: %s…", self.public_key_hex[:16]
        )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def public_key_hex(self) -> str:
        """Hex-encoded Ed25519 public key (identity)."""
        return self.crypto.public_key_bytes.hex()

    def export_private_key(self) -> bytes:
        """Raw private key bytes suitable for persistent storage."""
        return private_key_to_bytes(self.crypto.private_key)

    @classmethod
    def from_saved_key(cls, group_password: str, raw_private_key: bytes) -> "P2PGroupNode":
        """
        Restore a node from a previously exported private key.

        Args:
            group_password:  Shared group secret.
            raw_private_key: Bytes returned by :meth:`export_private_key`.
        """
        private_key = private_key_from_bytes(raw_private_key)
        return cls(group_password, private_key)

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def prepare_message(
        self,
        text: str,
        file_path: Optional[str] = None,
    ) -> dict:
        """
        Compose a network-ready encrypted packet.

        Args:
            text:      Plaintext message body.
            file_path: Optional path to an attachment.

        Returns:
            Dict with hex-encoded crypto fields plus top-level
            ``id`` and ``timestamp`` for CRDT comparisons.
        """
        attachment = None
        if file_path:
            if not os.path.exists(file_path):
                logger.warning("Attachment not found: %s", file_path)
            else:
                attachment = {
                    "name": os.path.basename(file_path),
                    "sha256": hash_file(file_path),
                    "size": os.path.getsize(file_path),
                }

        inner_data = {
            "id": str(uuid.uuid4()),
            "text": text,
            "attachment": attachment,
            "timestamp": int(time.time()),
        }

        packet = self.crypto.encrypt_and_sign(inner_data)
        # Expose id + timestamp at the top level for routing / CRDT
        packet["id"] = inner_data["id"]
        packet["timestamp"] = inner_data["timestamp"]
        return packet

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def receive_message(
        self,
        db,
        packet: dict,
    ) -> Optional[dict]:
        """
        Verify, decrypt, and CRDT-merge an incoming packet.

        Args:
            db:     Open SQLite connection (from :func:`storage.init_db`).
            packet: Raw dict received from the network layer.

        Returns:
            Decrypted inner data dict if accepted, None if rejected.
        """
        if not self.crypto.verify_packet(packet):
            logger.warning(
                "Rejected packet from %s… – invalid signature",
                packet.get("creator_pubkey", "?")[:12],
            )
            return None

        inner = self.crypto.decrypt(packet)
        if inner is None:
            logger.warning("Could not decrypt packet")
            return None

        # Ensure top-level CRDT fields are present
        full_msg = {**packet, **inner}
        merge_message(db, full_msg)
        return inner
