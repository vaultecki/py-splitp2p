# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Network Layer – P2P Expense Synchronisation

Zwei Protokolle:

1. GossipSub  ("/splitp2p/expenses/1.0")
   Jeder Node publiziert neue oder geänderte Ausgaben als JSON-Paket:
       { "id": str, "timestamp": int, "blob": hex }
   Der blob ist das AES-GCM-verschlüsselte Expense-Objekt aus crypto.py.
   Empfänger führen einen CRDT-Merge durch. Ohne das Gruppenpasswort
   ist der Blob für Fremde wertlos.

2. Direct Stream  ("/splitp2p/files/1.0")
   Dateianhänge werden on-demand per direktem Stream übertragen.
   Anfrage: SHA-256-Hex (32 Bytes UTF-8)
   Antwort: Rohdaten der Datei (chunk-weise)
   Nach dem Download: SHA-256-Verifikation – bei Abweichung wird verworfen.

Offline-Modus: läuft libp2p nicht oder ist es nicht installiert, bleibt
alles lokal funktionsfähig. Die GUI erhält in beiden Fällen Callbacks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

EXPENSE_PROTOCOL = "/splitp2p/expenses/1.0"
FILE_PROTOCOL    = "/splitp2p/files/1.0"
STORAGE_DIR      = "storage"
CHUNK_SIZE       = 16_384   # 16 KB


# ---------------------------------------------------------------------------
# Callbacks-Protokoll (wird von der GUI implementiert)
# ---------------------------------------------------------------------------

class NetworkCallbacks:
    """
    Interface das die GUI (oder ein Test-Stub) implementiert.
    Alle Methoden werden aus dem asyncio-Thread aufgerufen –
    gui.py leitet sie per `root.after(0, ...)` in den Tk-Thread weiter.
    """
    def on_expense_received(self, expense_id: str, blob: bytes) -> None:
        """Neuer oder aktualisierter Expense-Blob empfangen."""

    def on_peer_connected(self, peer_id: str) -> None:
        """Neuer Peer verbunden."""

    def on_peer_disconnected(self, peer_id: str) -> None:
        """Peer getrennt."""

    def on_status_changed(self, online: bool, peer_id: str) -> None:
        """Verbindungsstatus geändert."""

    def on_file_received(self, sha256: str) -> None:
        """Dateianhang erfolgreich empfangen und verifiziert."""


# ---------------------------------------------------------------------------
# Hauptklasse
# ---------------------------------------------------------------------------

class P2PNetwork:
    """
    Verwaltet den libp2p-Host, GossipSub-Subscriptions und File-Streams.

    Verwendung::

        net = P2PNetwork(group_password, callbacks)
        # Im asyncio-Thread starten:
        await net.start()

    Oder über start_in_thread() direkt aus synchronem Code.
    """

    def __init__(self, group_password: str, callbacks: NetworkCallbacks):
        from currency import group_topic_id  # sha256[:16] des Passworts

        # Topic-ID: nicht reversibel, kein Rückschluss auf Passwort möglich
        self.topic_id   = "splitp2p-" + group_topic_id(group_password)
        self.callbacks  = callbacks
        self._host      = None
        self._pubsub    = None
        self._sub       = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running   = False
        self._peers: set[str] = set()
        os.makedirs(STORAGE_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_in_thread(self) -> None:
        """
        Startet den P2P-Node in einem Daemon-Thread.
        Kehrt sofort zurück; der Node läuft im Hintergrund.
        """
        import threading
        t = threading.Thread(
            target=self._thread_main,
            daemon=True,
            name="p2p-network",
        )
        t.start()

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run())
        except Exception as e:
            logger.error("P2P thread crashed: %s", e)
        finally:
            self.callbacks.on_status_changed(online=False, peer_id="")

    async def _run(self) -> None:
        try:
            from libp2p import new_host
            from libp2p.pubsub import gossipsub
            from libp2p.pubsub.pubsub import Pubsub
        except ImportError:
            logger.warning(
                "libp2p nicht installiert – P2P-Sync deaktiviert. "
                "Installieren mit: pip install libp2p"
            )
            self.callbacks.on_status_changed(online=False, peer_id="offline-mode")
            return

        self._host = new_host()
        gossip     = gossipsub.GossipSub(["/meshsub/1.1.0"])
        self._pubsub = Pubsub(self._host, gossip)

        async with self._host.run():
            peer_id = self._host.get_id().to_string()
            self._running = True
            logger.info("P2P node started. Peer ID: %s", peer_id)

            self._sub = await self._pubsub.subscribe(self.topic_id)
            self._host.set_stream_handler(FILE_PROTOCOL, self._file_serve_handler)
            # Peer-Event-Hooks (falls libp2p das unterstützt)
            self._host.get_network().notify(self._PeerNotifee(self))

            self.callbacks.on_status_changed(online=True, peer_id=peer_id)
            logger.info("Subscribed to topic: %s", self.topic_id)

            await self._receive_loop()

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("P2P node stopping")

    # ------------------------------------------------------------------
    # Innere Klasse: Peer-Event-Notifier
    # ------------------------------------------------------------------

    class _PeerNotifee:
        """Minimaler libp2p Notifee für Connect/Disconnect-Events."""

        def __init__(self, network: "P2PNetwork"):
            self._net = network

        def connected(self, net, conn):
            pid = conn.get_remote_peer_id().to_string()
            self._net._peers.add(pid)
            logger.info("Peer connected: %s", pid[:16])
            self._net.callbacks.on_peer_connected(pid)

        def disconnected(self, net, conn):
            pid = conn.get_remote_peer_id().to_string()
            self._net._peers.discard(pid)
            logger.info("Peer disconnected: %s", pid[:16])
            self._net.callbacks.on_peer_disconnected(pid)

        # libp2p erwartet diese Methoden auch wenn sie leer sind
        def listen(self, *_): pass
        def listen_close(self, *_): pass
        def open_stream(self, *_): pass
        def close_stream(self, *_): pass

    # ------------------------------------------------------------------
    # GossipSub – Empfangsschleife
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        while self._running and self._sub is not None:
            try:
                msg = await asyncio.wait_for(self._sub.get(), timeout=1.0)
                await self._handle_expense_packet(msg)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error("Receive loop error: %s", e)

    async def _handle_expense_packet(self, msg) -> None:
        """Eingehendes GossipSub-Paket verarbeiten."""
        try:
            packet = json.loads(msg.data.decode())
            expense_id = packet["id"]
            blob       = bytes.fromhex(packet["blob"])
            timestamp  = int(packet["timestamp"])
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Malformed expense packet: %s", e)
            return

        logger.debug(
            "Received expense packet id=%s ts=%d from %s",
            expense_id[:8], timestamp, str(msg.from_id)[:12],
        )
        self.callbacks.on_expense_received(expense_id, blob)

    # ------------------------------------------------------------------
    # GossipSub – Senden
    # ------------------------------------------------------------------

    def publish_expense(self, expense_id: str, blob: bytes, timestamp: int) -> None:
        """
        Publiziert einen Expense-Blob im Gruppen-Topic.
        Thread-safe: kann aus dem Tk-Thread aufgerufen werden.
        """
        if self._loop is None or not self._running:
            logger.debug("publish_expense: offline, skipping")
            return
        packet = json.dumps({
            "id":        expense_id,
            "timestamp": timestamp,
            "blob":      blob.hex(),
        })
        asyncio.run_coroutine_threadsafe(
            self._publish(packet.encode()),
            self._loop,
        )

    async def _publish(self, data: bytes) -> None:
        if self._pubsub is not None:
            await self._pubsub.publish(self.topic_id, data)
            logger.debug("Published %d bytes to %s", len(data), self.topic_id)

    # ------------------------------------------------------------------
    # File Transfer – Serving side
    # ------------------------------------------------------------------

    async def _file_serve_handler(self, stream) -> None:
        """
        Eingehende Datei-Anfrage bearbeiten.
        Erwartet SHA-256-Hex → sendet Dateiinhalt in Chunks.
        """
        try:
            req_data  = await stream.read()
            sha256    = req_data.decode().strip()
            if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256):
                logger.warning("Invalid file request: %r", sha256[:20])
                return

            file_path = os.path.join(STORAGE_DIR, sha256)
            if not os.path.exists(file_path):
                logger.info("Requested file not available locally: %s", sha256[:12])
                return

            logger.info("Serving file %s…", sha256[:12])
            with open(file_path, "rb") as f:
                while chunk := f.read(CHUNK_SIZE):
                    await stream.write(chunk)
            logger.info("File %s served successfully", sha256[:12])

        except Exception as e:
            logger.error("File serve error: %s", e)
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # File Transfer – Requesting side
    # ------------------------------------------------------------------

    async def _download_file(self, peer_id_str: str, sha256: str) -> bool:
        """
        Datei von einem bestimmten Peer anfordern und SHA-256 verifizieren.
        Gibt True zurück wenn erfolgreich und Hash korrekt.
        """
        from libp2p.peer.id import ID as PeerID

        try:
            peer_id = PeerID.from_base58(peer_id_str)
            stream  = await self._host.new_stream(peer_id, [FILE_PROTOCOL])
        except Exception as e:
            logger.warning("Cannot open file stream to %s: %s", peer_id_str[:12], e)
            return False

        temp_path = os.path.join(STORAGE_DIR, sha256 + ".tmp")
        h = hashlib.sha256()
        try:
            await stream.write(sha256.encode())
            with open(temp_path, "wb") as f:
                while True:
                    chunk = await asyncio.wait_for(stream.read(), timeout=30.0)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)

            if h.hexdigest() == sha256:
                os.rename(temp_path, os.path.join(STORAGE_DIR, sha256))
                logger.info("File %s downloaded and verified", sha256[:12])
                self.callbacks.on_file_received(sha256)
                return True
            else:
                logger.error("Hash mismatch for %s – discarded", sha256[:12])
                os.remove(temp_path)
                return False

        except asyncio.TimeoutError:
            logger.warning("Timeout downloading %s from %s", sha256[:12], peer_id_str[:12])
        except Exception as e:
            logger.error("Download error for %s: %s", sha256[:12], e)
        finally:
            try:
                await stream.close()
            except Exception:
                pass
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        return False

    def request_file(self, sha256: str) -> None:
        """
        Fordert eine Datei von einem der bekannten Peers an.
        Probiert alle verbundenen Peers der Reihe nach durch.
        Thread-safe.
        """
        if not self._peers or not self._running:
            logger.debug("request_file: no peers available")
            return

        async def _try_peers():
            for peer_id in list(self._peers):
                ok = await self._download_file(peer_id, sha256)
                if ok:
                    return
            logger.warning("File %s not available from any peer", sha256[:12])

        asyncio.run_coroutine_threadsafe(_try_peers(), self._loop)

    # ------------------------------------------------------------------
    # Status-Abfragen
    # ------------------------------------------------------------------

    @property
    def is_online(self) -> bool:
        return self._running and self._host is not None

    @property
    def peer_id(self) -> Optional[str]:
        if self._host:
            return self._host.get_id().to_string()
        return None

    @property
    def peer_count(self) -> int:
        return len(self._peers)

    def known_peers(self) -> list[str]:
        return list(self._peers)
