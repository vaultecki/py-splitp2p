# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Network Layer - P2P Expense Sync

py-libp2p nutzt trio als Async-Backend (ab ~0.2).
This code runs in a daemon thread via trio.run().

Thread-Kommunikation:
  tkinter  ->  Trio   : queue.SimpleQueue (outgoing packets + commands)
  Trio     ->  tkinter: callbacks.on_*()  (werden in tkinter via root.after gerufen)

Drei Protokolle:
  /splitp2p/sync/1.0     – GossipSub (Expenses, Settlements, Members)
  /splitp2p/files/1.0    - direct stream: SHA-256 request -> binary data
  /splitp2p/history/1.0  – Direkt-Stream: Delta-Sync beim Peer-Connect

NAT-Traversal-Stack (alle optional, graceful fallback):
  AutoNAT           – Erkennt ob wir hinter NAT/Firewall sind
  Circuit Relay v2  - connections via public IPFS relay nodes
  Kademlia DHT      – Topic-ID im weltweiten DHT advertisen und suchen;
                      findet Gruppenmitglieder ohne direktes Treffen
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

SYNC_PROTOCOL = "/splitp2p/sync/1.0"
FILE_PROTOCOL = "/splitp2p/files/1.0"
HISTORY_PROTOCOL = "/splitp2p/history/1.0"
CHUNK_SIZE = 16_384
P2P_PORT = 8000  # fixed port so mDNS advertises the correct address
# change if 4001 is already in use on your system
DOWNLOAD_RETRIES = 3  # max Versuche pro Peer
RETRY_BACKOFF = (1, 3, 7)  # Wartezeit in Sekunden zwischen Versuchen

IPFS_BOOTSTRAP = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
]


def _build_listen_addrs(port: int) -> list:
    """
    Returns multiaddrs for both IPv4 and IPv6 wildcard interfaces.

    /ip4/0.0.0.0/tcp/<port>   - all IPv4 interfaces
    /ip6/::/tcp/<port>         - all IPv6 interfaces (link-local + GUA)

    Having both means the node accepts connections from either
    protocol version, and mDNS discovery works on whichever the
    local network supports.

    Falls back gracefully if get_available_interfaces() is available
    (it returns per-interface addrs which is more specific, but
    IPv4-only on most versions).
    """
    import multiaddr as _ma
    addrs = []
    # Always add explicit IPv4 + IPv6 wildcards first
    addrs.append(_ma.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}"))
    try:
        addrs.append(_ma.Multiaddr(f"/ip6/::/tcp/{port}"))
    except Exception:
        pass  # multiaddr version doesn't support ip6 syntax
    # Try to also add per-interface addrs from libp2p helper
    try:
        from libp2p.utils.address_validation import get_available_interfaces
        extra = get_available_interfaces(port)
        # Avoid duplicates: only add if not already covered
        seen = {str(a) for a in addrs}
        for a in extra:
            if str(a) not in seen:
                addrs.append(a)
    except Exception:
        pass
    return addrs


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

    def on_comment_received(self, comment_id: str, expense_id: str,
                            blob: bytes) -> None: pass

    def on_history_synced(self, n_expenses: int, n_settlements: int) -> None: pass


# ---------------------------------------------------------------------------
# P2PNetwork
# ---------------------------------------------------------------------------

class P2PNetwork:
    def __init__(self, group_password: str, callbacks: NetworkCallbacks):
        self.callbacks = callbacks
        self.callbacks = callbacks
        self._group_pw = group_password  # for blob verification
        self._group_salt = b""  # wird von gui.py gesetzt
        self._host = None
        self._pubsub = None
        self._sub = None
        self._running = False
        self._peers: set[str] = set()
        # Thread-safe queue: tkinter -> trio
        # Items: dicts mit "cmd" key:
        #   {"cmd": "publish",  "data": bytes}
        #   {"cmd": "req_file", "sha256": str}
        #   {"cmd": "req_history"}
        #   {"cmd": "stop"}
        self._cmd_queue: _queue.SimpleQueue = _queue.SimpleQueue()
        self._dht = None
        self._autonat = None
        self._relay = None
        self._behind_nat = True  # assume worst case until AutoNAT checks
        # Storage dir is configured via storage.configure_paths() before start
        # Do NOT hardcode "storage" here - use the configured path
        from storage import STORAGE_DIR
        os.makedirs(STORAGE_DIR, exist_ok=True)

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
            logger.warning("libp2p not installed - offline mode (%s)", e)
            self.callbacks.on_status_changed(False, "offline-mode")
            return

        import trio

        # Listen on both IPv4 and IPv6 so the node works in
        # IPv4-only, IPv6-only, and dual-stack LAN environments.
        # mDNS uses ff02::fb (IPv6) or 224.0.0.251 (IPv4);
        # libp2p picks whichever interface is available.
        listen_addrs = _build_listen_addrs(P2P_PORT)
        logger.info("Listening on: %s",
                    ", ".join(str(a) for a in listen_addrs))

        # new_host with mDNS if supported by installed version
        try:
            self._host = new_host(
                listen_addrs=listen_addrs,
                enable_mDNS=True,
            )
            logger.info("new_host() with built-in mDNS")
        except TypeError:
            self._host = new_host()
            logger.info("new_host() without mDNS (older API) - "
                        "will use manual mDNS fallback")

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
                logger.info("P2P node started, peer ID: %s", peer_id)

                self._sub = await self._pubsub.subscribe(self.topic_id)
                self._host.set_stream_handler(FILE_PROTOCOL, self._file_serve_handler)
                self._host.set_stream_handler(HISTORY_PROTOCOL, self._history_serve_handler)

                # Peer discovery via polling (works across all py-libp2p versions)
                # notify() was removed in newer versions; polling the peerstore
                # is the reliable cross-version alternative.

                self.callbacks.on_status_changed(True, peer_id)

                async with trio.open_nursery() as nursery:
                    nursery.start_soon(self._receive_loop)
                    nursery.start_soon(self._cmd_loop)
                    nursery.start_soon(self._connect_bootstrap)
                    nursery.start_soon(self._cleanup_stale_tmp)
                    nursery.start_soon(self._setup_mdns)
                    nursery.start_soon(self._peer_poll_loop)

        except Exception as e:
            logger.error("P2P run error: %s", e)
            self.callbacks.on_status_changed(False, "")

    def set_group_salt(self, salt: bytes) -> None:
        """
        Sets the group salt and derives the topic ID from it.
        Must be called BEFORE start_in_thread().
        Topic ID = SHA256(salt)[:16] - random, not guessable from password.
        """
        from crypto import group_topic_id
        self._group_salt = salt
        self.topic_id = "splitp2p-" + group_topic_id(salt)
        logger.info("Topic ID set: %s", self.topic_id)

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

    async def _peer_poll_loop(self) -> None:
        """
        Polls the GossipSub mesh every 2 seconds for peers sharing
        our topic. Only peers in our mesh are SplitP2P group members;
        bootstrap nodes (Qm... IDs) are excluded automatically because
        they don't subscribe to our group topic.
        """
        import trio
        own_id = self._host.get_id().to_string()
        logger.info("Peer poll loop started")
        while self._running:
            try:
                current: set[str] = set()

                # Primary: GossipSub mesh peers for our topic
                # These are the only peers that share our group.
                try:
                    mesh_peers = self._pubsub.router.mesh.get(
                        self.topic_id, set())
                    for pid in mesh_peers:
                        pid_str = pid.to_string() \
                            if hasattr(pid, 'to_string') else str(pid)
                        if pid_str != own_id:
                            current.add(pid_str)
                except Exception:
                    pass

                # Fallback: peers in peerstore that are not bootstrap nodes.
                # connections_with_peer() is unreliable across py-libp2p
                # versions so we skip that check and treat any known
                # non-bootstrap peer as a candidate. GossipSub will naturally
                # stop delivering messages from peers that disconnect.
                if not current:
                    try:
                        for pid in self._host.get_peerstore().peer_ids():
                            pid_str = pid.to_string() \
                                if hasattr(pid, 'to_string') else str(pid)
                            if pid_str == own_id:
                                continue
                            # Skip legacy DHT-only bootstrap nodes (Qm... prefix)
                            if pid_str.startswith("Qm"):
                                continue
                            current.add(pid_str)
                    except Exception as e:
                        logger.debug("Peerstore poll error: %s", e)

                # Fire callbacks for changes
                new_peers = current - self._peers
                gone_peers = self._peers - current

                if new_peers:
                    logger.debug("Poll: %d known, %d new, %d gone",
                                 len(current), len(new_peers), len(gone_peers))
                for pid in new_peers:
                    self._peers.add(pid)
                    self.callbacks.on_peer_connected(pid)
                    self._cmd_queue.put({"cmd": "req_history_from",
                                         "peer_id": pid})
                    # Re-announce our member info to the new peer
                    self._cmd_queue.put({"cmd": "announce_member"})
                    logger.info("Group peer connected: %s", pid[:20])

                for pid in gone_peers:
                    self._peers.discard(pid)
                    self.callbacks.on_peer_disconnected(pid)
                    logger.info("Group peer disconnected: %s", pid[:20])

            except Exception as e:
                logger.debug("Peer poll loop error: %s", e)

            await trio.sleep(2.0)

    async def _setup_mdns(self) -> None:
        """
        Manual mDNS discovery - fallback for py-libp2p versions
        that don't support enable_mDNS=True in new_host().
        Silently skipped if the module is not available.
        """
        import trio
        try:
            from libp2p.discovery.mdns import MDNSService
            service_name = f"_splitp2p_{self.topic_id[:8]}._udp.local."
            mdns = MDNSService(self._host, service_name=service_name)
            await mdns.start()
            logger.info("Manual mDNS discovery started (service: %s)",
                        self.topic_id[:8])
        except ImportError:
            logger.debug("libp2p.discovery.mdns not available - "
                         "mDNS disabled (already using built-in or not supported)")
        except Exception as e:
            logger.warning("mDNS setup failed: %s", e)

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
                ma = multiaddr.Multiaddr(addr_str)
                peer_info = info_from_p2p_addr(ma)
                with trio.move_on_after(10):
                    await self._host.connect(peer_info)
                    connected += 1
                    logger.info("Bootstrap connected: %s", addr_str.split("/")[-1][:16])
            except Exception as e:
                logger.debug("Bootstrap %s failed: %s", addr_str[-30:], e)

        logger.info("Bootstrap: %d/%d nodes reached", connected, len(IPFS_BOOTSTRAP))

        # Nach Bootstrap: DHT + NAT-Traversal starten
        await self._setup_nat_traversal()

    async def _setup_nat_traversal(self) -> None:
        """
        Aktiviert AutoNAT, Circuit Relay v2 und Kademlia DHT.
        Alle drei sind optional – fehlendes Modul -> graceful skip.

        AutoNAT:      erkennt ob wir direkt erreichbar sind.
        Circuit Relay: falls NAT erkannt -> Reservierung bei IPFS-Relay-Nodes.
        Kademlia DHT: advertise + find topic_id im globalen Netz;
                      Peers selber Gruppe finden sich ohne Bootstrap.
        """
        import trio

        # ── Kademlia DHT ────────────────────────────────────────────
        try:
            from libp2p.kademlia.network import KademliaServer
            self._dht = KademliaServer(self._host)
            await self._dht.bootstrap(
                [(peer_id, addr)
                 for peer_id, addr in self._host.get_peerstore()
                 .peer_ids()[:8]]
            ) if hasattr(self._dht, 'bootstrap') else None
            # Topic-ID im DHT advertisen (Peers selber Gruppe finden uns)
            await self._dht.set(self.topic_id,
                                self._host.get_id().to_string())
            logger.info("Kademlia DHT active, topic advertised")
            # Andere Peers suchen die dieselbe Gruppe advertisen
            result = await self._dht.get(self.topic_id)
            if result:
                logger.info("DHT: group peer found: %s", str(result)[:40])
        except ImportError:
            logger.debug("libp2p.kademlia not available - DHT skipped")
        except Exception as e:
            logger.warning("Kademlia DHT error: %s", e)

        # ── AutoNAT ─────────────────────────────────────────────────
        try:
            from libp2p.autonat import AutoNATService
            self._autonat = AutoNATService(self._host)
            with trio.move_on_after(15):
                reachability = await self._autonat.probe_reachability()
            logger.info("AutoNAT reachability: %s", reachability)
            self._behind_nat = reachability != "public"
        except ImportError:
            logger.debug("libp2p.autonat not available - AutoNAT skipped")
            self._behind_nat = True  # assume worst case
        except Exception as e:
            logger.warning("AutoNAT error: %s", e)
            self._behind_nat = True

        # ── Circuit Relay v2 (nur wenn hinter NAT) ──────────────────
        if getattr(self, '_behind_nat', True):
            try:
                from libp2p.relay.circuit_v2 import CircuitRelayV2Client
                self._relay = CircuitRelayV2Client(self._host)
                # Reservierung bei einem der verbundenen Bootstrap-Peers
                with trio.move_on_after(20):
                    await self._relay.reserve()
                logger.info("Circuit Relay v2: reservation active")
            except ImportError:
                logger.debug("Circuit Relay v2 not available")
            except Exception as e:
                logger.warning("Circuit Relay v2 error: %s", e)

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

    def _verify_and_decode_blob(self, blob: bytes,
                                ptype: str) -> bool:
        """
        Decrypts the blob and verifies the Ed25519 signature.
        Returns True if valid, False if rejected.

        Ablauf:
          1. AES-GCM decrypt -> Expense/Settlement object
          2. Verify Ed25519 signature of payer/sender
          3. Nur bei Erfolg: True -> Callback wird aufgerufen

        Warum hier und nicht im GUI-Callback:
          Early verification prevents tampered blobs from ever
          reaching the DB or UI. Any peer in the network could
          otherwise send junk packets with a valid topic ID.
        """
        try:
            from crypto import (decrypt_expense, verify_expense,
                                decrypt_settlement, verify_settlement)
        except ImportError:
            return True  # crypto not available -> no filter

        try:
            if ptype == "expense":
                obj = decrypt_expense(blob, self._group_pw, self._group_salt)
                if obj is None:
                    logger.warning("Expense blob not decryptable "
                                   "(falscher Key oder korrupt)")
                    return False
                if not verify_expense(obj):
                    logger.warning("Invalid signature on expense %s "
                                   "– verworfen", obj.id[:8])
                    return False
                # Creator integrity: payer_pubkey must never change.
                # The Ed25519 signature already guarantees this cryptographically -
                # an attacker cannot change obj.payer_pubkey without breaking
                # the signature. This check is defense-in-depth:
                # it catches the case where someone signs a new blob with
                # a changed payer_pubkey but their own valid key.
                try:
                    from storage import DB_PATH as _dbp
                    import sqlite3 as _sq
                    _c = _sq.connect(_dbp, check_same_thread=False)
                    _r = _c.execute(
                        "SELECT blob FROM expenses WHERE id = ? AND is_deleted = 0",
                        (obj.id,)
                    ).fetchone()
                    _c.close()
                    if _r:
                        existing = decrypt_expense(
                            bytes(_r[0]), self._group_pw, self._group_salt)
                        if existing and existing.payer_pubkey != obj.payer_pubkey:
                            logger.warning(
                                "Expense %s: payer_pubkey changed - rejected",
                                obj.id[:8])
                            return False
                except Exception as _e:
                    logger.debug("Creator check DB error: %s", _e)

                logger.debug("Expense %s verified OK", obj.id[:8])
                return True

            elif ptype == "settlement":
                obj = decrypt_settlement(blob, self._group_pw, self._group_salt)
                if obj is None:
                    logger.warning("Settlement blob not decryptable")
                    return False
                if not verify_settlement(obj):
                    logger.warning("Invalid signature on settlement %s "
                                   "– verworfen", obj.id[:8])
                    return False
                logger.debug("Settlement %s verified OK", obj.id[:8])
                return True

            elif ptype == "comment":
                from crypto import decrypt_comment, verify_comment
                obj = decrypt_comment(blob, self._group_pw, self._group_salt)
                if obj is None:
                    logger.warning("Comment blob not decryptable")
                    return False
                if not verify_comment(obj):
                    logger.warning("Invalid signature on comment %s",
                                   obj.id[:8])
                    return False
                return True

        except Exception as e:
            logger.warning("Verifikation Fehler (%s): %s", ptype, e)
            return False

        return True  # member packets: no blob signature, no filter

    async def _dispatch(self, msg) -> None:
        try:
            packet = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Malformed packet: %s", e)
            return

        ptype = packet.get("type", "expense")
        logger.debug("GossipSub packet received: type=%s id=%s",
                     ptype, packet.get("id", "-")[:8])
        try:
            blob = bytes.fromhex(packet["blob"]) if "blob" in packet else b""
        except ValueError:
            logger.warning("Invalid hex blob in packet")
            return

        if ptype in ("expense", "settlement"):
            if not self._verify_and_decode_blob(blob, ptype):
                return  # invalid signature or wrong key - reject
            if ptype == "expense":
                self.callbacks.on_expense_received(packet["id"], blob)
            else:
                self.callbacks.on_settlement_received(packet["id"], blob)
        elif ptype == "comment":
            blob = bytes.fromhex(packet["blob"])
            if not self._verify_and_decode_blob(blob, "comment"):
                return
            self.callbacks.on_comment_received(
                packet["id"], packet["expense_id"], blob)
        elif ptype == "member":
            self.callbacks.on_member_received(packet["pubkey"], packet["data"])
        else:
            logger.debug("Unknown packet type: %s", ptype)

    # ------------------------------------------------------------------
    # Command loop (drains _cmd_queue in trio thread)
    # ------------------------------------------------------------------

    async def _cmd_loop(self) -> None:
        import trio

        # Wir öffnen eine Nursery für alle Hintergrundaufgaben dieser Schleife
        async with trio.open_nursery() as nursery:
            while self._running:
                try:
                    cmd = self._cmd_queue.get_nowait()

                    if cmd["cmd"] == "stop":
                        self._running = False
                        nursery.cancel_scope.cancel()  # Bricht alle laufenden Downloads etc. ab
                        return

                    elif cmd["cmd"] == "publish":
                        if self._pubsub:
                            # Senden geht schnell, wir lagern es trotzdem sauber aus
                            nursery.start_soon(self._pubsub.publish, self.topic_id, cmd["data"])

                    elif cmd["cmd"] == "req_file":
                        # Hilfsfunktion, um den Datei-Download in den Hintergrund zu schicken
                        async def bg_download(sha, peers):
                            for pid in peers:
                                if await self._download_file(pid, sha):
                                    break

                        nursery.start_soon(bg_download, cmd["sha256"], list(self._peers))

                    elif cmd["cmd"] == "req_history_from":
                        # Ab in den Hintergrund damit!
                        nursery.start_soon(self._request_history, cmd["peer_id"])

                    elif cmd["cmd"] == "announce_member":
                        self.callbacks.on_peer_connected("self")  # Löst im UI Update aus

                    elif cmd["cmd"] == "req_history_all":
                        for pid in list(self._peers):
                            nursery.start_soon(self._request_history, pid)

                    elif cmd["cmd"] == "connect":
                        nursery.start_soon(self._connect_addr, cmd["addr"])

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

    def publish_comment(self, comment_id: str, expense_id: str,
                        blob: bytes, timestamp: int) -> None:
        self._publish_raw(json.dumps({
            "type": "comment",
            "id": comment_id,
            "expense_id": expense_id,
            "timestamp": timestamp,
            "blob": blob.hex(),
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
        """
        Serves a file encrypted with AES-256-GCM.
        Each chunk is individually encrypted so the receiver can
        verify chunks as they arrive without buffering the whole file.
        Wire format per chunk: 4-byte big-endian length + nonce(12) + ciphertext
        Sentinel: 4 zero bytes (length=0) signals end of file.
        """
        import trio
        try:
            sha256 = (await stream.read(64)).decode().strip()
            if len(sha256) != 64:
                return
            from storage import STORAGE_DIR
            path = os.path.join(STORAGE_DIR, sha256)
            if not os.path.exists(path):
                return
            if not self._group_pw:
                logger.warning("File serve: no group key, sending unencrypted")
                # Fallback: send raw (no group context)
                with open(path, "rb") as f:
                    while chunk := f.read(CHUNK_SIZE):
                        await stream.write(chunk)
            else:
                from crypto import _group_aes_key
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                key = _group_aes_key(self._group_pw, self._group_salt)
                aes = AESGCM(key)
                with open(path, "rb") as f:
                    while chunk := f.read(CHUNK_SIZE):
                        nonce = os.urandom(12)
                        ct = aes.encrypt(nonce, chunk, None)
                        frame = nonce + ct
                        # 4-byte length prefix so receiver knows frame size
                        await stream.write(len(frame).to_bytes(4, 'big') + frame)
                # Sentinel: 4 zero bytes = end of file
                await stream.write(b'\x00\x00\x00\x00')
            logger.info("Served file %s (encrypted)", sha256[:12])
        except Exception as e:
            logger.error("File serve error: %s", repr(e))
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # File Transfer – Requesting
    # ------------------------------------------------------------------

    async def _connect_addr(self, addr_str: str) -> None:
        """Connect to a peer by multiaddr string."""
        import trio
        try:
            import multiaddr as _ma
            from libp2p.peer.peerinfo import info_from_p2p_addr
            ma = _ma.Multiaddr(addr_str)
            try:
                peer_info = info_from_p2p_addr(ma)
            except Exception:
                # addr without /p2p/... suffix - try direct
                from libp2p.peer.peerinfo import PeerInfo
                from libp2p.peer.id import ID
                peer_info = PeerInfo(ID(b''), [ma])
            with trio.move_on_after(15):
                await self._host.connect(peer_info)
                logger.info("Manual connect OK: %s", addr_str[-40:])
        except Exception as e:
            logger.warning("Manual connect failed %s: %s",
                           addr_str[-40:], e)

    async def _cleanup_stale_tmp(self) -> None:
        """
        Deletes all *.tmp files in the storage folder at startup.
        These are always from aborted downloads and always incomplete
        (the hash never matches).
        Runs once at startup as a Trio task.
        """
        from storage import STORAGE_DIR
        try:
            removed = 0
            for fname in os.listdir(STORAGE_DIR):
                if fname.endswith(".tmp"):
                    path = os.path.join(STORAGE_DIR, fname)
                    try:
                        os.remove(path)
                        removed += 1
                        logger.info("Stale .tmp removed: %s", fname)
                    except OSError as e:
                        logger.warning("Cannot remove .tmp %s: %s", fname, e)
            if removed:
                logger.info("Startup cleanup: removed %d stale .tmp file(s)",
                            removed)
        except Exception as e:
            logger.warning("Startup .tmp cleanup failed: %s", e)

    async def _download_file(self, peer_id_str: str, sha256: str) -> bool:
        """
        Downloads a file from a peer.
        Retry logic: up to DOWNLOAD_RETRIES attempts with exponential
        backoff. On hash mismatch or timeout the .tmp file is deleted
        and the next attempt starts fresh.
        """
        import trio
        from storage import STORAGE_DIR
        temp = os.path.join(STORAGE_DIR, sha256 + ".tmp")

        for attempt in range(DOWNLOAD_RETRIES):
            if attempt > 0:
                wait = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
                logger.info("File %s: attempt %d/%d in %ds...",
                            sha256[:12], attempt + 1, DOWNLOAD_RETRIES, wait)
                await trio.sleep(wait)

            stream = None
            try:
                from libp2p.peer.id import ID as PeerID

                # --- NEU: 15-Sekunden-Timeout für den Stream-Aufbau ---
                with trio.move_on_after(15) as cancel_scope:
                    stream = await self._host.new_stream(
                        PeerID.from_base58(peer_id_str), [FILE_PROTOCOL])

                if cancel_scope.cancelled_caught:
                    logger.warning("Timeout beim Verbindungsaufbau für Datei %s (Versuch %d)",
                                   sha256[:12], attempt + 1)
                    continue  # Timeout -> direkt nächster Versuch
                # ------------------------------------------------------

            except Exception as e:
                logger.warning("Cannot open file stream to %s: %s",
                               peer_id_str[:12], repr(e))
                continue  # try next attempt

            try:
                h = hashlib.sha256()
                await stream.write(sha256.encode())

                # Set up decryption if we have a group key
                aes = None
                if self._group_pw:
                    from crypto import _group_aes_key
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                    aes = AESGCM(_group_aes_key(
                        self._group_pw, self._group_salt))

                with open(temp, "wb") as f:
                    buf = b""
                    while True:
                        with trio.move_on_after(30) as cancel:
                            try:
                                data = await stream.read(CHUNK_SIZE + 200)
                            except TypeError:
                                data = await stream.read(
                                    max_size=CHUNK_SIZE + 200)
                        if cancel.cancelled_caught:
                            raise TimeoutError("chunk timeout after 30s")
                        if not data:
                            break
                        buf += data
                        # Process complete framed chunks
                        while len(buf) >= 4:
                            frame_len = int.from_bytes(buf[:4], 'big')
                            if frame_len == 0:  # EOF sentinel
                                buf = b""
                                break
                            if aes is None:
                                # Unencrypted fallback: treat data as raw
                                chunk = buf[:frame_len] if frame_len > 0 else b""
                                buf = buf[frame_len:]
                                f.write(chunk)
                                h.update(chunk)
                            else:
                                if len(buf) < 4 + frame_len:
                                    break  # wait for more data
                                frame = buf[4:4 + frame_len]
                                buf = buf[4 + frame_len:]
                                nonce, ct = frame[:12], frame[12:]
                                plain = aes.decrypt(nonce, ct, None)
                                f.write(plain)
                                h.update(plain)

                if h.hexdigest() == sha256:
                    os.rename(temp, os.path.join(STORAGE_DIR, sha256))
                    self.callbacks.on_file_received(sha256)
                    logger.info("File %s downloaded and decrypted (attempt %d)",
                                sha256[:12], attempt + 1)
                    return True

                logger.warning("Hash mismatch for %s (attempt %d/%d)",
                               sha256[:12], attempt + 1, DOWNLOAD_RETRIES)
                if os.path.exists(temp):
                    os.remove(temp)

            except Exception as e:
                logger.warning("Download error %s attempt %d: %s",
                               sha256[:12], attempt + 1, repr(e))
                if os.path.exists(temp):
                    os.remove(temp)
            finally:
                if stream:
                    try:
                        await stream.close()
                    except Exception:
                        pass

        logger.error("File %s failed after %d attempts",
                     sha256[:12], DOWNLOAD_RETRIES)
        return False

    def connect_to_peer(self, multiaddr_str: str) -> None:
        """
        Manually connect to a known peer.
        multiaddr_str examples:
          /ip4/192.168.1.42/tcp/8000/p2p/12D3KooW...
          /ip6/fe80::1/tcp/8000/p2p/12D3KooW...  (IPv6 link-local)
          /ip4/192.168.1.42/tcp/8000             (without peer ID)
        Thread-safe: schedules the connect in the trio event loop.
        """
        if self._running:
            self._cmd_queue.put({"cmd": "connect",
                                 "addr": multiaddr_str})

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
            req = json.loads(req_raw.decode())
            since = int(req.get("since_ts", 0))
            topic = req.get("topic", "")

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
            try:
                from storage import load_all_comment_blobs_since
                for cid, xid, cblob in load_all_comment_blobs_since(since):
                    line = json.dumps({"type": "comment", "id": cid,
                                       "expense_id": xid, "blob": cblob.hex()}) + "\n"
                    await stream.write(line.encode())
                    sent += 1
            except Exception as _ce:
                logger.debug("Comment history error: %s", _ce)

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

            # --- NEU: Strenger 15-Sekunden-Timeout für den Verbindungsaufbau ---
            with trio.move_on_after(15) as cancel_scope:
                stream = await self._host.new_stream(
                    PeerID.from_base58(peer_id_str), [HISTORY_PROTOCOL])

            if cancel_scope.cancelled_caught:
                logger.warning(f"Timeout beim History-Sync mit Peer {peer_id_str[:12]}")
                return
            # -------------------------------------------------------------------
        except Exception as e:
            logger.debug("Cannot open history stream to %s: %s", peer_id_str[:12], e)
            return

        try:
            # Request all records (since_ts=0) so we always get
            # the peer's full state. CRDT merge on our side discards
            # records we already have. This fixes the case where
            # both peers have disjoint records with similar timestamps.
            req = json.dumps({"since_ts": 0, "topic": self.topic_id})
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
                        pkt = json.loads(line.decode())
                        blob = bytes.fromhex(pkt["blob"])
                        ptype = pkt["type"]
                        if ptype in ("expense", "settlement", "comment"):
                            if not self._verify_and_decode_blob(blob, ptype):
                                logger.warning("History: Paket verworfen "
                                               "(invalid signature)")
                                continue
                        if ptype == "expense":
                            self.callbacks.on_expense_received(pkt["id"], blob)
                            n_exp += 1
                        elif ptype == "settlement":
                            self.callbacks.on_settlement_received(pkt["id"], blob)
                            n_set += 1
                        elif ptype == "comment":
                            self.callbacks.on_comment_received(
                                pkt["id"], pkt.get("expense_id", ""), blob)
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
    