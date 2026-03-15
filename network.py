# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Network Layer

Drei Protokolle:
  1. GossipSub  "/splitp2p/sync/1.0"
     Pakete mit type-Feld:
       {"type": "expense",    "id": ..., "timestamp": ..., "blob": hex}
       {"type": "settlement", "id": ..., "timestamp": ..., "blob": hex}
       {"type": "member",     "pubkey": ..., "data": {display_name, joined_at}}

  2. Direct Stream  "/splitp2p/files/1.0"
     SHA-256-Anfrage → Binärdaten

  3. Peer-Discovery
     a) mDNS  – automatisch im lokalen Netz (kein Bootstrap nötig)
     b) IPFS-Bootstrap-Nodes – öffentliche libp2p-Knoten für das Internet

Alle Callbacks kommen aus dem asyncio-Thread.
gui.py leitet sie per root.after(0, ...) in den Tk-Thread weiter.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _local_max_timestamp() -> int:
    """Modul-level Wrapper für storage.get_max_timestamp()."""
    try:
        from storage import get_max_timestamp
        return get_max_timestamp()
    except Exception:
        return 0


def load_all_expense_blobs_since(since: int):
    from storage import load_all_expense_blobs_since as _f
    return _f(since)


def load_all_settlement_blobs_since(since: int):
    from storage import load_all_settlement_blobs_since as _f
    return _f(since)


SYNC_PROTOCOL = "/splitp2p/sync/1.0"
FILE_PROTOCOL    = "/splitp2p/files/1.0"
HISTORY_PROTOCOL = "/splitp2p/history/1.0"
CHUNK_SIZE       = 16_384

# Öffentliche libp2p / IPFS Bootstrap-Knoten
IPFS_BOOTSTRAP = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
]


# ---------------------------------------------------------------------------
# Callbacks-Interface
# ---------------------------------------------------------------------------

class NetworkCallbacks:
    def on_expense_received(self, expense_id: str, blob: bytes) -> None: pass
    def on_settlement_received(self, settlement_id: str, blob: bytes) -> None: pass
    def on_member_received(self, pubkey: str, data: dict) -> None: pass
    def on_peer_connected(self, peer_id: str) -> None: pass
    def on_peer_disconnected(self, peer_id: str) -> None: pass
    def on_status_changed(self, online: bool, peer_id: str) -> None: pass
    def on_file_received(self, sha256: str) -> None: pass
    def on_history_synced(self, n_expenses: int, n_settlements: int) -> None: pass


# ---------------------------------------------------------------------------
# P2PNetwork
# ---------------------------------------------------------------------------

class P2PNetwork:
    def __init__(self, group_password: str, callbacks: NetworkCallbacks):
        from crypto import group_topic_id
        self.topic_id   = "splitp2p-" + group_topic_id(group_password)
        self.callbacks  = callbacks
        self._host      = None
        self._pubsub    = None
        self._sub       = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running   = False
        self._peers: set[str] = set()
        os.makedirs("storage", exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_in_thread(self) -> None:
        import threading
        threading.Thread(
            target=self._thread_main, daemon=True, name="p2p-network"
        ).start()

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run())
        except Exception as e:
            logger.error("P2P thread crashed: %s", e)
        finally:
            self.callbacks.on_status_changed(False, "")

    async def _run(self) -> None:
        try:
            from libp2p import new_host
            from libp2p.pubsub import gossipsub
            from libp2p.pubsub.pubsub import Pubsub
        except ImportError:
            logger.warning("libp2p not installed – offline mode")
            self.callbacks.on_status_changed(False, "offline-mode")
            return

        self._host   = new_host()
        gossip       = gossipsub.GossipSub(["/meshsub/1.1.0"])
        self._pubsub = Pubsub(self._host, gossip)

        async with self._host.run():
            peer_id   = self._host.get_id().to_string()
            self._running = True
            logger.info("P2P node started. PeerID: %s", peer_id)

            self._sub = await self._pubsub.subscribe(self.topic_id)
            self._host.set_stream_handler(FILE_PROTOCOL, self._file_serve_handler)
            self._host.set_stream_handler(HISTORY_PROTOCOL, self._history_serve_handler)
            self._host.get_network().notify(self._PeerNotifee(self))

            self.callbacks.on_status_changed(True, peer_id)

            # Discovery starten (parallel, Fehler sind nicht fatal)
            asyncio.create_task(self._setup_mdns())
            asyncio.create_task(self._connect_bootstrap())

            await self._receive_loop()

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ------------------------------------------------------------------
    # Peer-Discovery: mDNS
    # ------------------------------------------------------------------

    async def _setup_mdns(self) -> None:
        """
        mDNS-Discovery für lokale Netze.
        Peers im selben LAN mit demselben topic_id finden sich automatisch.
        """
        try:
            from libp2p.discovery.mdns import MDNSService
            mdns = MDNSService(
                self._host,
                service_name=f"_splitp2p_{self.topic_id[:8]}._udp.local.",
            )
            await mdns.start()
            logger.info("mDNS discovery started (service: %s)", self.topic_id[:8])
        except ImportError:
            logger.debug("libp2p mDNS module not available – skipping local discovery")
        except Exception as e:
            logger.warning("mDNS setup failed: %s", e)

    # ------------------------------------------------------------------
    # Peer-Discovery: IPFS Bootstrap
    # ------------------------------------------------------------------

    async def _connect_bootstrap(self) -> None:
        """
        Verbindet mit öffentlichen IPFS-Bootstrap-Nodes.
        Das reicht um ins globale libp2p-DHT einzutreten und
        andere SplitP2P-Nodes zu finden, die dieselbe Topic-ID abonniert haben.
        """
        try:
            import multiaddr
            from libp2p.peer.peerinfo import info_from_p2p_addr
        except ImportError:
            logger.debug("multiaddr not available – bootstrap skipped")
            return

        connected = 0
        for addr_str in IPFS_BOOTSTRAP:
            try:
                ma        = multiaddr.Multiaddr(addr_str)
                peer_info = info_from_p2p_addr(ma)
                await asyncio.wait_for(
                    self._host.connect(peer_info), timeout=10.0
                )
                connected += 1
                logger.info("Bootstrap connected: %s", addr_str.split("/")[-1][:16])
            except asyncio.TimeoutError:
                logger.debug("Bootstrap timeout: %s", addr_str[-30:])
            except Exception as e:
                logger.debug("Bootstrap %s failed: %s", addr_str[-30:], e)

        logger.info("Bootstrap: %d/%d nodes reached", connected, len(IPFS_BOOTSTRAP))

    # ------------------------------------------------------------------
    # GossipSub – Receive
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        while self._running and self._sub is not None:
            try:
                msg = await asyncio.wait_for(self._sub.get(), timeout=1.0)
                await self._dispatch(msg)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error("Receive loop error: %s", e)

    async def _dispatch(self, msg) -> None:
        try:
            packet = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Malformed packet: %s", e)
            return

        ptype = packet.get("type", "expense")

        if ptype == "expense":
            blob = bytes.fromhex(packet["blob"])
            self.callbacks.on_expense_received(packet["id"], blob)

        elif ptype == "settlement":
            blob = bytes.fromhex(packet["blob"])
            self.callbacks.on_settlement_received(packet["id"], blob)

        elif ptype == "member":
            self.callbacks.on_member_received(packet["pubkey"], packet["data"])

        else:
            logger.debug("Unknown packet type: %s", ptype)

    # ------------------------------------------------------------------
    # GossipSub – Publish
    # ------------------------------------------------------------------

    def _publish_raw(self, data: bytes) -> None:
        if not self._running or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._do_publish(data), self._loop)

    async def _do_publish(self, data: bytes) -> None:
        if self._pubsub:
            await self._pubsub.publish(self.topic_id, data)

    def publish_expense(self, expense_id: str, blob: bytes, timestamp: int) -> None:
        self._publish_raw(json.dumps({
            "type":      "expense",
            "id":        expense_id,
            "timestamp": timestamp,
            "blob":      blob.hex(),
        }).encode())

    def publish_settlement(self, settlement_id: str, blob: bytes, timestamp: int) -> None:
        self._publish_raw(json.dumps({
            "type":      "settlement",
            "id":        settlement_id,
            "timestamp": timestamp,
            "blob":      blob.hex(),
        }).encode())

    def publish_member(self, pubkey: str, display_name: str, joined_at: int) -> None:
        self._publish_raw(json.dumps({
            "type":        "member",
            "pubkey":      pubkey,
            "data":        {"display_name": display_name, "joined_at": joined_at},
        }).encode())

    # ------------------------------------------------------------------
    # File Transfer – Serve
    # ------------------------------------------------------------------

    async def _file_serve_handler(self, stream) -> None:
        try:
            sha256    = (await stream.read()).decode().strip()
            if len(sha256) != 64:
                return
            from storage import STORAGE_DIR
            path = os.path.join(STORAGE_DIR, sha256)
            if not os.path.exists(path):
                return
            with open(path, "rb") as f:
                while chunk := f.read(CHUNK_SIZE):
                    await stream.write(chunk)
            logger.info("Served file %s", sha256[:12])
        except Exception as e:
            logger.error("File serve error: %s", e)
        finally:
            try: await stream.close()
            except Exception: pass

    # ------------------------------------------------------------------
    # File Transfer – Request
    # ------------------------------------------------------------------

    async def _download_file(self, peer_id_str: str, sha256: str) -> bool:
        import hashlib as _hl
        from libp2p.peer.id import ID as PeerID
        from storage import STORAGE_DIR
        try:
            stream = await self._host.new_stream(
                PeerID.from_base58(peer_id_str), [FILE_PROTOCOL]
            )
        except Exception as e:
            logger.warning("Cannot open file stream to %s: %s", peer_id_str[:12], e)
            return False

        temp = os.path.join(STORAGE_DIR, sha256 + ".tmp")
        h    = _hl.sha256()
        try:
            await stream.write(sha256.encode())
            with open(temp, "wb") as f:
                while True:
                    chunk = await asyncio.wait_for(stream.read(), timeout=30.0)
                    if not chunk: break
                    f.write(chunk); h.update(chunk)
            if h.hexdigest() == sha256:
                os.rename(temp, os.path.join(STORAGE_DIR, sha256))
                self.callbacks.on_file_received(sha256)
                return True
            logger.error("Hash mismatch for %s", sha256[:12])
            os.remove(temp)
            return False
        except Exception as e:
            logger.error("Download error %s: %s", sha256[:12], e)
            if os.path.exists(temp): os.remove(temp)
            return False
        finally:
            try: await stream.close()
            except Exception: pass

    def request_file(self, sha256: str) -> None:
        if not self._peers or not self._running: return
        async def _try():
            for pid in list(self._peers):
                if await self._download_file(pid, sha256): return
        asyncio.run_coroutine_threadsafe(_try(), self._loop)

    # ------------------------------------------------------------------
    # Peer events
    # ------------------------------------------------------------------

    class _PeerNotifee:
        def __init__(self, net):
            self._net = net
        def connected(self, _, conn):
            pid = conn.get_remote_peer_id().to_string()
            self._net._peers.add(pid)
            self._net.callbacks.on_peer_connected(pid)
            # Sofort History vom neuen Peer anfordern
            asyncio.run_coroutine_threadsafe(
                self._net._request_history(pid),
                self._net._loop,
            ) if self._net._loop else None
        def disconnected(self, _, conn):
            pid = conn.get_remote_peer_id().to_string()
            self._net._peers.discard(pid)
            self._net.callbacks.on_peer_disconnected(pid)
        def listen(self, *_): pass
        def listen_close(self, *_): pass
        def open_stream(self, *_): pass
        def close_stream(self, *_): pass

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # History Sync – Serving side
    # ------------------------------------------------------------------

    async def _history_serve_handler(self, stream) -> None:
        """
        Antwortet auf eine History-Anfrage.

        Protokoll:
          Anfrage:  JSON {"since_ts": int, "topic": str}
          Antwort:  Zeilenweise JSON-Pakete (ein Blob pro Zeile), dann Leerzeile als EOF.
                    Jede Zeile: {"type": "expense"|"settlement", "id": ..., "blob": hex, "ts": int}
        """
        try:
            req_raw = await asyncio.wait_for(stream.read(), timeout=10.0)
            req     = json.loads(req_raw.decode())
            since   = int(req.get("since_ts", 0))
            topic   = req.get("topic", "")

            # Nur antworten wenn Topic übereinstimmt (Gruppenpasswort-Ableitung)
            if topic != self.topic_id:
                logger.debug("History request for wrong topic, ignoring")
                await stream.close()
                return

            from storage import load_all_expense_blobs, load_all_settlement_blobs
            import sqlite3

            # Hole alle Blobs – CRDT-Timestamp liegt in der DB-Tabelle
            sent = 0
            for eid, blob in load_all_expense_blobs_since(since):
                line = json.dumps({"type": "expense",
                                   "id": eid, "blob": blob.hex()}) + "\n"
                await stream.write(line.encode())
                sent += 1
            for sid, blob in load_all_settlement_blobs_since(since):
                line = json.dumps({"type": "settlement",
                                   "id": sid, "blob": blob.hex()}) + "\n"
                await stream.write(line.encode())
                sent += 1

            # EOF-Marker
            await stream.write(b"\n")
            logger.info("History: served %d records since ts=%d", sent, since)

        except Exception as e:
            logger.error("History serve error: %s", e)
        finally:
            try: await stream.close()
            except Exception: pass

    # ------------------------------------------------------------------
    # History Sync – Requesting side
    # ------------------------------------------------------------------

    async def _request_history(self, peer_id_str: str) -> None:
        """
        Fordert alle Expense- und Settlement-Blobs vom Peer an
        die neuer als unser höchster bekannter Timestamp sind.
        """
        try:
            from libp2p.peer.id import ID as PeerID
            stream = await asyncio.wait_for(
                self._host.new_stream(PeerID.from_base58(peer_id_str),
                                      [HISTORY_PROTOCOL]),
                timeout=10.0,
            )
        except Exception as e:
            logger.debug("Cannot open history stream to %s: %s",
                         peer_id_str[:12], e)
            return

        try:
            # Unseren aktuellen höchsten Timestamp ermitteln
            since = _local_max_timestamp()
            req   = json.dumps({"since_ts": since, "topic": self.topic_id})
            await stream.write(req.encode())

            # Zeilenweise lesen bis Leerzeile (EOF-Marker)
            buf = b""
            n_exp = n_set = 0
            while True:
                chunk = await asyncio.wait_for(stream.read(), timeout=30.0)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        # EOF-Marker
                        self.callbacks.on_history_synced(n_exp, n_set)
                        return
                    try:
                        pkt = json.loads(line.decode())
                        blob = bytes.fromhex(pkt["blob"])
                        if pkt["type"] == "expense":
                            self.callbacks.on_expense_received(pkt["id"], blob)
                            n_exp += 1
                        elif pkt["type"] == "settlement":
                            self.callbacks.on_settlement_received(pkt["id"], blob)
                            n_set += 1
                    except Exception as e:
                        logger.warning("History parse error: %s", e)

            self.callbacks.on_history_synced(n_exp, n_set)
            logger.info("History: received %d expenses + %d settlements from %s",
                        n_exp, n_set, peer_id_str[:12])

        except asyncio.TimeoutError:
            logger.warning("History request timeout from %s", peer_id_str[:12])
        except Exception as e:
            logger.error("History request error: %s", e)
        finally:
            try: await stream.close()
            except Exception: pass

    def request_history_from_all(self) -> None:
        """Fordert History von allen bekannten Peers an (Thread-safe)."""
        if not self._peers or not self._running: return
        async def _do():
            for pid in list(self._peers):
                await self._request_history(pid)
        asyncio.run_coroutine_threadsafe(_do(), self._loop)

    @property
    def is_online(self) -> bool:
        return self._running and self._host is not None

    @property
    def peer_id(self) -> Optional[str]:
        return self._host.get_id().to_string() if self._host else None

    @property
    def peer_count(self) -> int:
        return len(self._peers)

    def known_peers(self) -> list[str]:
        return list(self._peers)
