# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Network Layer – P2P Expense Synchronisation

py-libp2p nutzt trio als Async-Backend (ab ~0.2).
Dieser Code läuft daher in einem Daemon-Thread mit trio.run().

Thread-Kommunikation:
  tkinter  →  Trio   : queue.SimpleQueue (outgoing packets + commands)
  Trio     →  tkinter: callbacks.on_*()  (werden in tkinter via root.after gerufen)

Drei Protokolle:
  /splitp2p/sync/1.0     – GossipSub (Expenses, Settlements, Members)
  /splitp2p/files/1.0    – Direkt-Stream: SHA-256-Anfrage → Binärdaten
  /splitp2p/history/1.0  – Direkt-Stream: Delta-Sync beim Peer-Connect
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue as _queue
import threading
from typing import Optional

logger = logging.getLogger(__name__)

SYNC_PROTOCOL    = "/splitp2p/sync/1.0"
FILE_PROTOCOL    = "/splitp2p/files/1.0"
HISTORY_PROTOCOL = "/splitp2p/history/1.0"
CHUNK_SIZE       = 16_384

IPFS_BOOTSTRAP = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
]


def _local_max_timestamp() -> int:
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


# ---------------------------------------------------------------------------
# Callbacks
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
        self._running   = False
        self._peers: set[str] = set()
        # Thread-safe queue: tkinter → trio
        # Items: dicts mit "cmd" key:
        #   {"cmd": "publish",  "data": bytes}
        #   {"cmd": "req_file", "sha256": str}
        #   {"cmd": "req_history"}
        #   {"cmd": "stop"}
        self._cmd_queue: _queue.SimpleQueue = _queue.SimpleQueue()
        os.makedirs("storage", exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_in_thread(self) -> None:
        threading.Thread(
            target=self._thread_main,
            daemon=True,
            name="p2p-network",
        ).start()

    def _thread_main(self) -> None:
        try:
            import trio
            trio.run(self._run)
        except ImportError:
            logger.warning("trio not installed – offline mode")
            self.callbacks.on_status_changed(False, "offline-mode")
        except Exception as e:
            logger.error("P2P thread crashed: %s", e)
            self.callbacks.on_status_changed(False, "")

    async def _run(self) -> None:
        try:
            import trio
            from libp2p import new_host
            from libp2p.pubsub import gossipsub
            from libp2p.pubsub.pubsub import Pubsub
            from libp2p.utils.address_validation import get_available_interfaces
        except ImportError as e:
            logger.warning("libp2p not installed – offline mode (%s)", e)
            self.callbacks.on_status_changed(False, "offline-mode")
            return

        import trio

        # listen_addrs: Port 0 → OS wählt freien Port
        try:
            listen_addrs = get_available_interfaces(0)
        except Exception:
            import multiaddr
            listen_addrs = [multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")]

        # new_host mit mDNS (aktuelle API)
        try:
            self._host = new_host(
                listen_addrs=listen_addrs,
                enable_mDNS=True,
            )
        except TypeError:
            self._host = new_host()

        # GossipSub
        gossip = gossipsub.GossipSub(
            protocols=["/meshsub/1.1.0"],
            degree=6,
            degree_low=4,
            degree_high=12,
        )
        self._pubsub = Pubsub(self._host, gossip)

        # Nursery statt asyncio.create_task
        try:
            async with self._host.run(listen_addrs=listen_addrs):
                peer_id = self._host.get_id().to_string()
                self._running = True
                logger.info("P2P node started. PeerID: %s", peer_id)

                self._sub = await self._pubsub.subscribe(self.topic_id)
                self._host.set_stream_handler(FILE_PROTOCOL,    self._file_serve_handler)
                self._host.set_stream_handler(HISTORY_PROTOCOL, self._history_serve_handler)

                # Peer-Events (API variiert je nach Version)
                try:
                    self._host.get_network().notify(self._PeerNotifee(self))
                except Exception as e:
                    logger.debug("notify() not available: %s", e)

                self.callbacks.on_status_changed(True, peer_id)

                async with trio.open_nursery() as nursery:
                    nursery.start_soon(self._receive_loop)
                    nursery.start_soon(self._cmd_loop)
                    nursery.start_soon(self._connect_bootstrap)

        except Exception as e:
            logger.error("P2P run error: %s", e)
            self.callbacks.on_status_changed(False, "")

    def stop(self) -> None:
        self._running = False
        self._cmd_queue.put({"cmd": "stop"})
        logger.info("P2P node stopping")

    # ------------------------------------------------------------------
    # Peer events
    # ------------------------------------------------------------------

    class _PeerNotifee:
        def __init__(self, net):
            self._net = net

        def connected(self, _, conn):
            import trio
            pid = conn.get_remote_peer_id().to_string()
            self._net._peers.add(pid)
            self._net.callbacks.on_peer_connected(pid)
            # History anfordern
            self._net._cmd_queue.put({"cmd": "req_history_from", "peer_id": pid})

        def disconnected(self, _, conn):
            pid = conn.get_remote_peer_id().to_string()
            self._net._peers.discard(pid)
            self._net.callbacks.on_peer_disconnected(pid)

        def listen(self, *_): pass
        def listen_close(self, *_): pass
        def open_stream(self, *_): pass
        def close_stream(self, *_): pass

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    async def _connect_bootstrap(self) -> None:
        import trio
        try:
            import multiaddr
            from libp2p.peer.peerinfo import info_from_p2p_addr
        except ImportError:
            return

        connected = 0
        for addr_str in IPFS_BOOTSTRAP:
            try:
                ma        = multiaddr.Multiaddr(addr_str)
                peer_info = info_from_p2p_addr(ma)
                with trio.move_on_after(10):
                    await self._host.connect(peer_info)
                    connected += 1
                    logger.info("Bootstrap: %s", addr_str.split("/")[-1][:16])
            except Exception as e:
                logger.debug("Bootstrap %s failed: %s", addr_str[-30:], e)

        logger.info("Bootstrap: %d/%d nodes reached", connected, len(IPFS_BOOTSTRAP))

    # ------------------------------------------------------------------
    # GossipSub – Empfangen
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        import trio
        while self._running and self._sub is not None:
            try:
                with trio.move_on_after(1.0):
                    msg = await self._sub.get()
                    if msg is not None:
                        await self._dispatch(msg)
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
            self.callbacks.on_expense_received(
                packet["id"], bytes.fromhex(packet["blob"]))
        elif ptype == "settlement":
            self.callbacks.on_settlement_received(
                packet["id"], bytes.fromhex(packet["blob"]))
        elif ptype == "member":
            self.callbacks.on_member_received(packet["pubkey"], packet["data"])
        else:
            logger.debug("Unknown packet type: %s", ptype)

    # ------------------------------------------------------------------
    # Command loop (drains _cmd_queue in trio thread)
    # ------------------------------------------------------------------

    async def _cmd_loop(self) -> None:
        import trio
        while self._running:
            try:
                cmd = self._cmd_queue.get_nowait()
                if cmd["cmd"] == "stop":
                    self._running = False
                    return
                elif cmd["cmd"] == "publish":
                    if self._pubsub:
                        await self._pubsub.publish(self.topic_id, cmd["data"])
                elif cmd["cmd"] == "req_file":
                    for pid in list(self._peers):
                        ok = await self._download_file(pid, cmd["sha256"])
                        if ok:
                            break
                elif cmd["cmd"] == "req_history_from":
                    await self._request_history(cmd["peer_id"])
                elif cmd["cmd"] == "req_history_all":
                    for pid in list(self._peers):
                        await self._request_history(pid)
            except _queue.Empty:
                await trio.sleep(0.05)
            except Exception as e:
                logger.error("Command loop error: %s", e)
                await trio.sleep(0.1)

    # ------------------------------------------------------------------
    # GossipSub – Senden (thread-safe, von tkinter aufrufbar)
    # ------------------------------------------------------------------

    def _publish_raw(self, data: bytes) -> None:
        if self._running:
            self._cmd_queue.put({"cmd": "publish", "data": data})

    def publish_expense(self, expense_id: str, blob: bytes, timestamp: int) -> None:
        self._publish_raw(json.dumps({
            "type": "expense", "id": expense_id,
            "timestamp": timestamp, "blob": blob.hex(),
        }).encode())

    def publish_settlement(self, settlement_id: str, blob: bytes, timestamp: int) -> None:
        self._publish_raw(json.dumps({
            "type": "settlement", "id": settlement_id,
            "timestamp": timestamp, "blob": blob.hex(),
        }).encode())

    def publish_member(self, pubkey: str, display_name: str, joined_at: int) -> None:
        self._publish_raw(json.dumps({
            "type": "member", "pubkey": pubkey,
            "data": {"display_name": display_name, "joined_at": joined_at},
        }).encode())

    # ------------------------------------------------------------------
    # File Transfer – Serving
    # ------------------------------------------------------------------

    async def _file_serve_handler(self, stream) -> None:
        import trio
        try:
            sha256 = (await stream.read(64)).decode().strip()
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
            try:
                await stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # File Transfer – Requesting
    # ------------------------------------------------------------------

    async def _download_file(self, peer_id_str: str, sha256: str) -> bool:
        import trio
        from storage import STORAGE_DIR
        try:
            from libp2p.peer.id import ID as PeerID
            stream = await self._host.new_stream(
                PeerID.from_base58(peer_id_str), [FILE_PROTOCOL])
        except Exception as e:
            logger.warning("Cannot open file stream to %s: %s", peer_id_str[:12], e)
            return False

        temp = os.path.join(STORAGE_DIR, sha256 + ".tmp")
        h    = hashlib.sha256()
        try:
            await stream.write(sha256.encode())
            with open(temp, "wb") as f:
                while True:
                    with trio.move_on_after(30) as cancel:
                        chunk = await stream.read(CHUNK_SIZE)
                    if cancel.cancelled_caught:
                        raise TimeoutError("download timeout")
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)

            if h.hexdigest() == sha256:
                os.rename(temp, os.path.join(STORAGE_DIR, sha256))
                self.callbacks.on_file_received(sha256)
                logger.info("File %s downloaded OK", sha256[:12])
                return True
            logger.error("Hash mismatch for %s", sha256[:12])
            os.remove(temp)
            return False
        except Exception as e:
            logger.error("Download error %s: %s", sha256[:12], e)
            if os.path.exists(temp):
                os.remove(temp)
            return False
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    def request_file(self, sha256: str) -> None:
        if self._peers and self._running:
            self._cmd_queue.put({"cmd": "req_file", "sha256": sha256})

    # ------------------------------------------------------------------
    # History Sync – Serving
    # ------------------------------------------------------------------

    async def _history_serve_handler(self, stream) -> None:
        import trio
        try:
            req_raw = await stream.read(4096)
            req     = json.loads(req_raw.decode())
            since   = int(req.get("since_ts", 0))
            topic   = req.get("topic", "")

            if topic != self.topic_id:
                logger.debug("History request for wrong topic")
                return

            sent = 0
            for eid, blob in load_all_expense_blobs_since(since):
                line = json.dumps({
                    "type": "expense", "id": eid, "blob": blob.hex()
                }) + "\n"
                await stream.write(line.encode())
                sent += 1
            for sid, blob in load_all_settlement_blobs_since(since):
                line = json.dumps({
                    "type": "settlement", "id": sid, "blob": blob.hex()
                }) + "\n"
                await stream.write(line.encode())
                sent += 1

            await stream.write(b"\n")  # EOF marker
            logger.info("History: served %d records since ts=%d", sent, since)

        except Exception as e:
            logger.error("History serve error: %s", e)
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # History Sync – Requesting
    # ------------------------------------------------------------------

    async def _request_history(self, peer_id_str: str) -> None:
        import trio
        try:
            from libp2p.peer.id import ID as PeerID
            stream = await self._host.new_stream(
                PeerID.from_base58(peer_id_str), [HISTORY_PROTOCOL])
        except Exception as e:
            logger.debug("Cannot open history stream to %s: %s", peer_id_str[:12], e)
            return

        try:
            since = _local_max_timestamp()
            req   = json.dumps({"since_ts": since, "topic": self.topic_id})
            await stream.write(req.encode())

            buf = b""
            n_exp = n_set = 0
            while True:
                with trio.move_on_after(30) as cancel:
                    chunk = await stream.read(CHUNK_SIZE)
                if cancel.cancelled_caught:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        self.callbacks.on_history_synced(n_exp, n_set)
                        return
                    try:
                        pkt  = json.loads(line.decode())
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
            logger.info("History: +%d expenses +%d settlements from %s",
                        n_exp, n_set, peer_id_str[:12])

        except Exception as e:
            logger.error("History request error from %s: %s", peer_id_str[:12], e)
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    def request_history_from_all(self) -> None:
        if self._running:
            self._cmd_queue.put({"cmd": "req_history_all"})

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

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
