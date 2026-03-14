# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Network Layer Module

Wraps libp2p GossipSub for group messaging and a direct-stream
protocol for peer-to-peer file transfers.

Falls back to "offline mode" when libp2p is not installed, so the
rest of the application (including the GUI) remains functional.
"""

import asyncio
import hashlib
import json
import logging
import os
from typing import Callable, Optional

from crypto import topic_id_from_password

logger = logging.getLogger(__name__)

STORAGE_DIR = "./storage"
FILE_PROTOCOL = "/p2p-chat/file-sync/1.0"


class P2PNetwork:
    """
    Manages the libp2p host, GossipSub subscriptions, and file streams.

    Usage::

        async def on_message(packet: dict):
            ...  # called for every validated incoming packet

        net = P2PNetwork("my-group-password", on_message)
        await net.start()          # blocks until stopped
    """

    def __init__(self, group_password: str, on_message: Callable):
        self.topic_id = topic_id_from_password(group_password)
        self.on_message = on_message
        self.host = None
        self.pubsub = None
        self._sub = None
        self._running = False
        os.makedirs(STORAGE_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the libp2p node. Logs a warning and returns if unavailable."""
        try:
            from libp2p import new_host
            from libp2p.pubsub import gossipsub
            from libp2p.pubsub.pubsub import Pubsub
        except ImportError:
            logger.warning(
                "libp2p not installed – running in offline mode. "
                "Install with: pip install libp2p"
            )
            return

        self.host = new_host()
        gossip = gossipsub.GossipSub(["/meshsub/1.1.0"])
        self.pubsub = Pubsub(self.host, gossip)

        async with self.host.run():
            self._running = True
            peer_id = self.host.get_id().to_string()
            logger.info("Node started. Peer ID: %s", peer_id)

            self._sub = await self.pubsub.subscribe(self.topic_id)
            self.host.set_stream_handler(FILE_PROTOCOL, self._file_request_handler)
            logger.info("Subscribed to topic: %s", self.topic_id)

            await self._receive_loop()

    def stop(self) -> None:
        """Signal the receive loop to exit."""
        self._running = False
        logger.info("Network node stopping")

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def publish(self, packet: dict) -> bool:
        """
        Publish an encrypted packet to the group topic.

        Returns:
            True on success, False if not connected.
        """
        if self.pubsub is None:
            logger.debug("publish called in offline mode – ignored")
            return False
        data = json.dumps(packet).encode()
        await self.pubsub.publish(self.topic_id, data)
        logger.debug("Published %d bytes to topic %s", len(data), self.topic_id)
        return True

    async def _receive_loop(self) -> None:
        while self._running and self._sub is not None:
            try:
                msg = await asyncio.wait_for(self._sub.get(), timeout=1.0)
                try:
                    packet = json.loads(msg.data.decode())
                    await self.on_message(packet)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.warning("Malformed packet: %s", e)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error("Receive loop error: %s", e)

    # ------------------------------------------------------------------
    # File transfer – serving side
    # ------------------------------------------------------------------

    async def _file_request_handler(self, stream) -> None:
        """Respond to an incoming file-request stream."""
        try:
            request_data = await stream.read()
            file_hash = request_data.decode().strip()
            logger.info("File request for hash: %s", file_hash)

            file_path = os.path.join(STORAGE_DIR, file_hash)
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    while chunk := f.read(16_384):
                        await stream.write(chunk)
                logger.info("Served file %s", file_hash)
            else:
                logger.warning("Requested file not found: %s", file_hash)
        except Exception as e:
            logger.error("File stream error: %s", e)
        finally:
            await stream.close()

    # ------------------------------------------------------------------
    # File transfer – downloading side
    # ------------------------------------------------------------------

    async def download_file(self, peer_id: str, target_hash: str) -> bool:
        """
        Download a file from a specific peer and verify its hash.

        Args:
            peer_id:     Libp2p peer ID string.
            target_hash: Expected SHA-256 hex digest of the file.

        Returns:
            True if download succeeded and hash matched, False otherwise.
        """
        if self.host is None:
            logger.warning("download_file called in offline mode")
            return False
        try:
            stream = await self.host.new_stream(peer_id, [FILE_PROTOCOL])
            await stream.write(target_hash.encode())

            temp_path = os.path.join(STORAGE_DIR, f"{target_hash}.tmp")
            sha256 = hashlib.sha256()

            with open(temp_path, "wb") as f:
                while True:
                    chunk = await stream.read()
                    if not chunk:
                        break
                    f.write(chunk)
                    sha256.update(chunk)

            if sha256.hexdigest() == target_hash:
                final_path = os.path.join(STORAGE_DIR, target_hash)
                os.rename(temp_path, final_path)
                logger.info("File %s verified and saved", target_hash)
                return True
            else:
                os.remove(temp_path)
                logger.error("Hash mismatch for file %s – discarded", target_hash)
                return False

        except Exception as e:
            logger.error("Download failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Peers
    # ------------------------------------------------------------------

    def get_peer_id(self) -> Optional[str]:
        """Return own peer ID string, or None in offline mode."""
        if self.host:
            return self.host.get_id().to_string()
        return None

    def is_online(self) -> bool:
        """Return True if the network layer is running."""
        return self._running and self.host is not None
