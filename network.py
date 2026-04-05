# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Network Layer — P2P Expense Sync

py-libp2p uses trio as async backend.
Runs in a daemon thread via trio.run().

Thread communication:
  tkinter → Trio : queue.SimpleQueue (commands + outgoing packets)
  Trio → tkinter : callbacks.on_*()  (scheduled via root.after(0, ...))

Three protocols:
  /splitp2p/sync/1.0     — GossipSub broadcast (real-time updates)
  /splitp2p/files/1.0    — direct stream: SHA-256 request → encrypted chunks
  /splitp2p/history/1.0  — direct stream: delta sync via Lamport maps

Wire format for synced records:
  Encrypted: {"type": "expense"|"settlement"|"comment"|"attachment"|"split",
               "id": str, "timestamp": int, "data": hex(encrypt_record(...))}
  Plaintext: {"type": "user", "pubkey": str, "data": {...}, "signature": str}
  Users are not encrypted — display names visible to anyone with the topic UUID.
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
HISTORY_PROTOCOL = "/splitp2p/history/1.0"   # delta sync via Lamport maps
CHUNK_SIZE       = 16_384
P2P_PORT         = 8000
DOWNLOAD_RETRIES = 3
RETRY_BACKOFF    = (1, 3, 7)

IPFS_BOOTSTRAP = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
]


def _build_listen_addrs(port: int) -> list:
    import multiaddr as _ma
    addrs = [_ma.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")]
    try:
        addrs.append(_ma.Multiaddr(f"/ip6/::/tcp/{port}"))
    except Exception:
        pass
    try:
        from libp2p.utils.address_validation import get_available_interfaces
        seen = {str(a) for a in addrs}
        for a in get_available_interfaces(port):
            if str(a) not in seen:
                addrs.append(a)
    except Exception:
        pass
    return addrs


# ---------------------------------------------------------------------------
# Callbacks — all receive model objects, not blobs
# ---------------------------------------------------------------------------

class NetworkCallbacks:
    def on_expense_received(self, expense) -> None:       pass
    def on_settlement_received(self, settlement) -> None: pass
    def on_comment_received(self, comment) -> None:       pass
    def on_attachment_received(self, attachment) -> None: pass
    def on_split_received(self, split) -> None:           pass
    def on_user_received(self, user) -> None:             pass
    def on_peer_connected(self, peer_id: str) -> None:    pass
    def on_peer_disconnected(self, peer_id: str) -> None: pass
    def on_status_changed(self, online: bool,
                          peer_id: str) -> None:          pass
    def on_file_received(self, sha256: str) -> None:      pass
    def on_history_synced(self, counts: dict) -> None:    pass


# ---------------------------------------------------------------------------
# P2PNetwork
# ---------------------------------------------------------------------------

class P2PNetwork:
    def __init__(self, group_key: bytes, topic_id: str,
                 callbacks: NetworkCallbacks,
                 db=None, group_id: str = ""):
        self.callbacks      = callbacks
        self._group_key     = group_key    # 32-byte SecretBox key
        self.topic_id       = f"splitp2p-{topic_id}"
        self._db            = db           # sqlite3 connection for history sync
        self._group_id      = group_id     # for storage queries
        self._own_pubkey    = ""
        self._own_name      = ""
        self._own_joined_at = 0
        self._host          = None
        self._pubsub        = None
        self._sub           = None
        self._running       = False
        self._peers: set[str] = set()
        self._cmd_queue = _queue.SimpleQueue()
        logger.info("Topic ID set: %s", self.topic_id)

    def set_own_identity(self, pubkey: str, display_name: str,
                         joined_at: int) -> None:
        self._own_pubkey    = pubkey
        self._own_name      = display_name
        self._own_joined_at = joined_at

    def set_db(self, db, group_id: str) -> None:
        """Set DB connection and group_id for history sync handlers."""
        self._db       = db
        self._group_id = group_id

    def stop(self) -> None:
        self._running = False
        self._cmd_queue.put({"cmd": "stop"})

    def start_in_thread(self) -> None:
        t = threading.Thread(target=self._run, daemon=True, name="P2PNetwork")
        t.start()

    def _run(self) -> None:
        try:
            import trio
            trio.run(self._main)
        except Exception as e:
            logger.error("P2P thread crashed: %s", e)

    async def _main(self) -> None:
        import trio
        try:
            await self._start_node()
        except Exception as e:
            logger.error("P2P node start failed: %s", e)
            self.callbacks.on_status_changed(False, "offline-mode")
            return
        try:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._receive_loop)
                nursery.start_soon(self._cmd_loop)
                nursery.start_soon(self._peer_poll_loop)
                nursery.start_soon(self._bootstrap)
                nursery.start_soon(self._cleanup_stale_tmp)
        except Exception as e:
            logger.error("P2P nursery error: %s", e)
        finally:
            self.callbacks.on_status_changed(False, "")

    async def _start_node(self) -> None:
        import trio
        from libp2p import new_host
        from libp2p.crypto.secp256k1 import create_new_key_pair
        from libp2p.pubsub.gossipsub import GossipSub
        from libp2p.pubsub.pubsub import Pubsub

        listen_addrs = _build_listen_addrs(P2P_PORT)
        key_pair     = create_new_key_pair()

        try:
            self._host = new_host(
                key_pair=key_pair,
                listen_addrs=listen_addrs,
                enable_mDNS=True)
            logger.info("new_host() with built-in mDNS")
        except TypeError:
            self._host = new_host(
                key_pair=key_pair,
                listen_addrs=listen_addrs)
            logger.info("new_host() without mDNS arg")

        self._host.set_stream_handler(FILE_PROTOCOL,    self._file_serve_handler)
        self._host.set_stream_handler(HISTORY_PROTOCOL, self._history_serve_handler)

        gossipsub   = GossipSub()
        self._pubsub = Pubsub(self._host, gossipsub)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._host.run)
            nursery.start_soon(self._pubsub.run)
            await trio.sleep(2)

        peer_id = self._host.get_id().to_string()
        self._running = True
        listen_str    = ", ".join(str(a) for a in self._host.get_addrs())
        logger.info("Listening on: %s", listen_str)
        logger.info("P2P node started: %s  topic: %s", peer_id, self.topic_id)

        self._sub = await self._pubsub.subscribe(self.topic_id)
        self.callbacks.on_status_changed(True, peer_id)

    async def _bootstrap(self) -> None:
        import trio
        await trio.sleep(3)
        reached = 0
        for addr in IPFS_BOOTSTRAP:
            try:
                import multiaddr as _ma
                from libp2p.peer.peerinfo import info_from_p2p_addr
                ma   = _ma.Multiaddr(addr)
                info = info_from_p2p_addr(ma)
                with trio.move_on_after(5):
                    await self._host.connect(info)
                    reached += 1
            except Exception as e:
                logger.debug("Bootstrap %s failed: %s", addr[-30:], e)
        logger.info("Bootstrap: %d/%d nodes reached", reached, len(IPFS_BOOTSTRAP))
        self._setup_extras()

    def _setup_extras(self) -> None:
        try:
            import libp2p.discovery.mdns as _mdns
            _mdns.setup_mdns(self._host, self.topic_id)
        except Exception:
            logger.debug("libp2p.discovery.mdns not available - "
                         "mDNS disabled (already using built-in or not supported)")
        try:
            import libp2p.kademlia as _kad
            _kad.setup_dht(self._host)
        except Exception:
            logger.debug("libp2p.kademlia not available - DHT skipped")
        try:
            import libp2p.autonat as _nat
            _nat.setup_autonat(self._host)
        except Exception:
            logger.debug("libp2p.autonat not available - AutoNAT skipped")
        try:
            import libp2p.relay as _relay
            _relay.setup_circuit_relay_v2(self._host)
        except Exception:
            logger.debug("Circuit Relay v2 not available")

    # ------------------------------------------------------------------
    # Peer poll loop
    # ------------------------------------------------------------------

    async def _peer_poll_loop(self) -> None:
        import trio
        logger.info("Peer poll loop started")
        while self._running:
            await trio.sleep(2)
            try:
                current: set[str] = set()
                for pid in self._host.get_peerstore().peer_ids():
                    pid_str = str(pid)
                    if pid_str == str(self._host.get_id()):
                        continue
                    try:
                        protos = await self._host.get_mux(pid)
                        if not protos:
                            continue
                    except Exception:
                        pass
                    current.add(pid_str)

                # Also include peerstore fallback
                try:
                    for pid in self._host.get_peerstore().peer_ids():
                        pid_str = str(pid)
                        if pid_str != str(self._host.get_id()):
                            current.add(pid_str)
                except Exception:
                    pass

                new_peers  = current - self._peers
                gone_peers = self._peers - current

                if new_peers:
                    logger.debug("Poll: %d known, %d new, %d gone",
                                 len(current), len(new_peers), len(gone_peers))

                for pid in new_peers:
                    self._peers.add(pid)
                    self.callbacks.on_peer_connected(pid)
                    self._cmd_queue.put({"cmd": "req_history_from",
                                         "peer_id": pid})
                    self._cmd_queue.put({"cmd": "announce_member"})
                    logger.info("Group peer connected: %s", pid[:20])

                for pid in gone_peers:
                    self._peers.discard(pid)
                    self.callbacks.on_peer_disconnected(pid)
                    logger.info("Group peer disconnected: %s", pid[:20])

            except Exception as e:
                logger.debug("Peer poll loop error: %s", e)

    # ------------------------------------------------------------------
    # GossipSub receive loop
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

    def _decrypt_and_verify(self, data_hex: str, record_type,
                             pubkey_field: str = "author_pubkey") -> Optional[object]:
        """
        Decrypts an encrypted wire record and verifies its Ed25519 signature.
        Returns the model object on success, None on any failure.
        This happens before any callback is invoked — tampered or wrong-key
        packets never reach the DB.
        """
        from crypto import decrypt_record, verify_record
        try:
            blob   = bytes.fromhex(data_hex)
            record = decrypt_record(blob, self._group_key, record_type)
            if record is None:
                logger.warning("Decryption failed for %s", record_type.__name__)
                return None
            pubkey = getattr(record, pubkey_field, None)
            if not pubkey:
                logger.warning("Missing pubkey field '%s' on %s",
                               pubkey_field, record_type.__name__)
                return None
            if not verify_record(record, pubkey):
                return None
            return record
        except Exception as e:
            logger.warning("decrypt_and_verify(%s): %s",
                           record_type.__name__, repr(e))
            return None

    async def _dispatch(self, msg) -> None:
        from models import Expense, Settlement, UserComment, Attachment, Split, User
        try:
            packet = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Malformed packet: %s", e)
            return

        ptype = packet.get("type", "")
        logger.debug("GossipSub recv: type=%s id=%s",
                     ptype, packet.get("id", packet.get("pubkey", "-"))[:8])

        try:
            if ptype == "expense":
                rec = self._decrypt_and_verify(
                    packet["data"], Expense)
                if rec:
                    self.callbacks.on_expense_received(rec)

            elif ptype == "split":
                rec = self._decrypt_and_verify(
                    packet["data"], Split)
                if rec:
                    self.callbacks.on_split_received(rec)

            elif ptype == "settlement":
                rec = self._decrypt_and_verify(
                    packet["data"], Settlement)
                if rec:
                    self.callbacks.on_settlement_received(rec)

            elif ptype == "comment":
                rec = self._decrypt_and_verify(
                    packet["data"], UserComment)
                if rec:
                    self.callbacks.on_comment_received(rec)

            elif ptype == "attachment":
                rec = self._decrypt_and_verify(
                    packet["data"], Attachment)
                if rec:
                    self.callbacks.on_attachment_received(rec)

            elif ptype == "user":
                # User packets are plaintext — signed but not encrypted
                from crypto import _verify
                user = User.from_wire_dict(packet["user_data"])
                if _verify(user.canonical_bytes(),
                           packet.get("signature", ""),
                           user.public_key):
                    self.callbacks.on_user_received(user)
                else:
                    logger.warning("Invalid signature on user packet %s",
                                   user.public_key[:12])
            else:
                logger.debug("Unknown packet type: %s", ptype)

        except Exception as e:
            logger.warning("Dispatch error (%s): %s", ptype, repr(e))

    # ------------------------------------------------------------------
    # Command loop
    # ------------------------------------------------------------------

    async def _cmd_loop(self) -> None:
        import trio
        async with trio.open_nursery() as nursery:
            while self._running:
                try:
                    cmd = self._cmd_queue.get_nowait()

                    if cmd["cmd"] == "stop":
                        self._running = False
                        nursery.cancel_scope.cancel()
                        return

                    elif cmd["cmd"] == "publish":
                        if self._pubsub:
                            nursery.start_soon(
                                self._pubsub.publish,
                                self.topic_id, cmd["data"])

                    elif cmd["cmd"] == "req_file":
                        nursery.start_soon(
                            self._download_file_all_peers, cmd["sha256"])

                    elif cmd["cmd"] == "req_history_from":
                        nursery.start_soon(
                            self._request_history, cmd["peer_id"])

                    elif cmd["cmd"] == "announce_member":
                        if self._own_pubkey and self._pubsub:
                            nursery.start_soon(self._publish_user_announce)

                    elif cmd["cmd"] == "req_history_all":
                        for pid in list(self._peers):
                            nursery.start_soon(self._request_history, pid)

                    elif cmd["cmd"] == "push_delta":
                        nursery.start_soon(
                            self._push_delta,
                            cmd["peer_id"], cmd["server_map"])

                    elif cmd["cmd"] == "connect":
                        nursery.start_soon(self._connect_addr, cmd["addr"])

                except _queue.Empty:
                    await trio.sleep(0.05)
                except Exception as e:
                    logger.error("Command loop error: %s", e)
                    await trio.sleep(0.1)

    # ------------------------------------------------------------------
    # GossipSub — publish
    # ------------------------------------------------------------------

    def _publish_raw(self, data: bytes) -> None:
        if self._running:
            self._cmd_queue.put({"cmd": "publish", "data": data})

    def _make_packet(self, ptype: str, record, **extra) -> bytes:
        """Encrypt record and wrap in a GossipSub packet."""
        from crypto import encrypt_record
        blob = encrypt_record(record, self._group_key)
        pkt  = {"type": ptype, "id": record.id,
                "timestamp": record.timestamp, "data": blob.hex()}
        pkt.update(extra)
        return json.dumps(pkt).encode()

    def publish_expense(self, expense) -> None:
        self._publish_raw(self._make_packet("expense", expense))

    def publish_splits(self, splits: list) -> None:
        for s in splits:
            self._publish_raw(self._make_packet("split", s))

    def publish_settlement(self, settlement) -> None:
        self._publish_raw(self._make_packet("settlement", settlement))

    def publish_comment(self, comment) -> None:
        self._publish_raw(self._make_packet(
            "comment", comment, belongs_to=comment.belongs_to))

    def publish_attachment(self, attachment) -> None:
        self._publish_raw(self._make_packet(
            "attachment", attachment, belongs_to=attachment.belongs_to))

    async def _publish_user_announce(self) -> None:
        """User announce is plaintext + Ed25519 signed (not SecretBox encrypted)."""
        from models import User
        from crypto import sign_user
        from config_manager import ConfigManager
        try:
            user = User.create(self._own_pubkey, self._own_name,
                               self._group_id)
            cfg_path = ConfigManager()._config_path
            import json as _j
            raw_key = _j.load(open(cfg_path)).get("private_key_hex", "")
            if raw_key:
                from crypto import private_key_from_bytes, sign_record
                sk = private_key_from_bytes(bytes.fromhex(raw_key))
                user.signature = sign_record(user, sk)
            pkt = json.dumps({
                "type":      "user",
                "user_data": user.to_wire_dict(),
                "signature": user.signature,
            }).encode()
            await self._pubsub.publish(self.topic_id, pkt)
        except Exception as e:
            logger.warning("User announce failed: %s", e)

    def publish_member(self, pubkey: str, display_name: str,
                       joined_at: int) -> None:
        """Compatibility shim — triggers async user announce via cmd queue."""
        self._own_pubkey    = pubkey
        self._own_name      = display_name
        self._own_joined_at = joined_at
        self._cmd_queue.put({"cmd": "announce_member"})

    # ------------------------------------------------------------------
    # File Transfer — Serving
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
            from crypto import encrypt_chunk
            with open(path, "rb") as f:
                while chunk := f.read(CHUNK_SIZE):
                    frame = encrypt_chunk(chunk, self._group_key)
                    await stream.write(len(frame).to_bytes(4, "big") + frame)
            await stream.write(b"\x00\x00\x00\x00")  # EOF sentinel
            logger.info("Served file %s", sha256[:12])
        except Exception as e:
            logger.error("File serve error: %s", repr(e))
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # File Transfer — Downloading
    # ------------------------------------------------------------------

    async def _download_file_all_peers(self, sha256: str) -> None:
        for pid in list(self._peers):
            ok = await self._download_file(pid, sha256)
            if ok:
                return
        logger.warning("File %s unavailable from any of %d peers",
                       sha256[:12], len(self._peers))

    async def _download_file(self, peer_id_str: str, sha256: str) -> bool:
        import trio
        from storage import STORAGE_DIR
        temp = os.path.join(STORAGE_DIR, sha256 + ".tmp")

        for attempt in range(DOWNLOAD_RETRIES):
            if attempt > 0:
                wait = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
                logger.info("File %s: attempt %d/%d in %ds...",
                            sha256[:12], attempt + 1, DOWNLOAD_RETRIES, wait)
                await trio.sleep(wait)

            try:
                from libp2p.peer.id import ID as PeerID
                with trio.move_on_after(15) as cs:
                    stream = await self._host.new_stream(
                        PeerID.from_base58(peer_id_str), [FILE_PROTOCOL])
                if cs.cancelled_caught:
                    logger.warning("File stream open timeout for %s", sha256[:12])
                    continue
            except Exception as e:
                logger.warning("Cannot open file stream to %s: %s",
                               peer_id_str[:12], repr(e))
                continue

            try:
                from crypto import decrypt_chunk
                h = hashlib.sha256()
                await stream.write(sha256.encode())

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
                        while len(buf) >= 4:
                            frame_len = int.from_bytes(buf[:4], "big")
                            if frame_len == 0:   # EOF sentinel
                                buf = b""
                                break
                            if len(buf) < 4 + frame_len:
                                break
                            frame = buf[4:4 + frame_len]
                            buf   = buf[4 + frame_len:]
                            plain = decrypt_chunk(frame, self._group_key)
                            f.write(plain)
                            h.update(plain)

                if h.hexdigest() == sha256:
                    os.rename(temp, os.path.join(STORAGE_DIR, sha256))
                    self.callbacks.on_file_received(sha256)
                    logger.info("File %s downloaded (attempt %d)",
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
                try:
                    await stream.close()
                except Exception:
                    pass

        logger.error("File %s failed after %d attempts",
                     sha256[:12], DOWNLOAD_RETRIES)
        return False

    # ------------------------------------------------------------------
    # Misc async helpers
    # ------------------------------------------------------------------

    async def _connect_addr(self, addr_str: str) -> None:
        import trio
        try:
            import multiaddr as _ma
            from libp2p.peer.peerinfo import info_from_p2p_addr
            ma = _ma.Multiaddr(addr_str)
            try:
                peer_info = info_from_p2p_addr(ma)
            except Exception:
                from libp2p.peer.peerinfo import PeerInfo
                from libp2p.peer.id import ID
                peer_info = PeerInfo(ID(b""), [ma])
            with trio.move_on_after(15):
                await self._host.connect(peer_info)
                logger.info("Manual connect OK: %s", addr_str[-40:])
        except Exception as e:
            logger.warning("Manual connect failed %s: %s", addr_str[-40:], e)

    async def _cleanup_stale_tmp(self) -> None:
        from storage import STORAGE_DIR
        try:
            removed = 0
            for fname in os.listdir(STORAGE_DIR):
                if fname.endswith(".tmp"):
                    path = os.path.join(STORAGE_DIR, fname)
                    try:
                        os.remove(path)
                        removed += 1
                    except OSError:
                        pass
            if removed:
                logger.info("Startup cleanup: %d stale .tmp removed", removed)
        except Exception as e:
            logger.warning("Startup .tmp cleanup failed: %s", e)

    # ------------------------------------------------------------------
    # History Sync — Serving (delta via Lamport maps)
    # ------------------------------------------------------------------

    def _row_to_wire(self, row, ptype: str) -> Optional[bytes]:
        """
        Converts a sqlite3.Row to an encrypted wire packet.
        Returns None if encryption fails.
        is_stored is excluded for attachments (local-only field).
        """
        from crypto import encrypt_record
        from models import (Expense, Settlement, UserComment,
                            Attachment, Split, User)
        TYPE_MAP = {
            "expense":    Expense,
            "settlement": Settlement,
            "comment":    UserComment,
            "attachment": Attachment,
            "split":      Split,
            "user":       User,
        }
        cls = TYPE_MAP.get(ptype)
        if not cls:
            return None
        try:
            d = dict(row)
            # Remove local-only fields before serializing
            d.pop("is_stored", None)
            record = cls.from_wire_dict(d)
            return encrypt_record(record, self._group_key)
        except Exception as e:
            logger.warning("Row→wire failed (%s): %s", ptype, e)
            return None

    async def _history_serve_handler(self, stream) -> None:
        """
        Delta history sync.

        Request:  JSON {"topic": str, "known": {table: {id: lamport}, ...}}
        Response: line-delimited JSON, blank line = EOF
                  Last record before EOF: {"type":"lamport_map","map":{...}}
        """
        import trio
        try:
            req_raw = await stream.read(65536)
            req     = json.loads(req_raw.decode())
            topic   = req.get("topic", "")

            if topic != self.topic_id:
                logger.debug("History: wrong topic, ignoring")
                return

            if not self._db:
                logger.warning("History: no DB connection, cannot serve")
                await stream.write(b"\n")
                return

            from storage import get_lamport_map, get_records_unknown_to
            known = req.get("known", {})
            delta = get_records_unknown_to(self._db, known, self._group_id)
            sent  = 0

            type_map = [
                ("expense",    "expenses"),
                ("settlement", "settlements"),
                ("comment",    "comments"),
                ("split",      "splits"),
                ("attachment", "attachments"),
            ]

            for ptype, table_key in type_map:
                for row in delta.get(table_key, []):
                    blob = self._row_to_wire(row, ptype)
                    if blob is None:
                        continue
                    extra: dict = {}
                    if ptype in ("comment", "split", "attachment"):
                        extra["belongs_to"] = row["belongs_to"]
                    line = json.dumps({
                        "type":      ptype,
                        "id":        row["id"],
                        "timestamp": row["timestamp"],
                        "data":      blob.hex(),
                        **extra,
                    }) + "\n"
                    await stream.write(line.encode())
                    sent += 1

            # Users: plaintext + signed, composite key in id field
            for row in delta.get("users", []):
                d = dict(row)
                line = json.dumps({
                    "type":      "user",
                    "id":        f"{d['public_key']}:{d['group_id']}",
                    "timestamp": d["timestamp"],
                    "user_data": d,
                    "signature": d["signature"],
                }) + "\n"
                await stream.write(line.encode())
                sent += 1

            # Send own lamport map for bidirectional delta
            my_map = get_lamport_map(self._db, self._group_id)
            await stream.write(
                (json.dumps({"type": "lamport_map", "map": my_map}) + "\n").encode())

            await stream.write(b"\n")  # EOF
            logger.info("History: served %d records", sent)

        except Exception as e:
            logger.error("History serve error: %s", repr(e))
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # History Sync — Requesting
    # ------------------------------------------------------------------

    async def _request_history(self, peer_id_str: str) -> None:
        import trio
        from models import Expense, Settlement, UserComment, Attachment, Split, User
        try:
            from libp2p.peer.id import ID as PeerID
            with trio.move_on_after(15) as cs:
                stream = await self._host.new_stream(
                    PeerID.from_base58(peer_id_str), [HISTORY_PROTOCOL])
            if cs.cancelled_caught:
                logger.warning("History stream timeout to %s", peer_id_str[:12])
                return
        except Exception as e:
            logger.debug("Cannot open history stream to %s: %s",
                         peer_id_str[:12], e)
            return

        try:
            from storage import get_lamport_map
            if not self._db:
                logger.warning("History request: no DB connection")
                return
            my_map = get_lamport_map(self._db, self._group_id)
            req    = json.dumps({"topic": self.topic_id, "known": my_map})
            await stream.write(req.encode())

            buf        = b""
            counts     = {k: 0 for k in
                          ("expenses","settlements","comments",
                           "splits","attachments","users")}
            server_map = None

            while True:
                with trio.move_on_after(30) as cancel:
                    chunk = await stream.read(CHUNK_SIZE)
                if cancel.cancelled_caught or not chunk:
                    break
                buf += chunk

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():   # EOF
                        self.callbacks.on_history_synced(counts)
                        if server_map:
                            self._cmd_queue.put({
                                "cmd":        "push_delta",
                                "peer_id":    peer_id_str,
                                "server_map": server_map,
                            })
                        return

                    try:
                        pkt   = json.loads(line.decode())
                        ptype = pkt.get("type", "")

                        if ptype == "lamport_map":
                            server_map = pkt.get("map", {})
                            continue

                        if ptype == "user":
                            from crypto import _verify
                            ud   = pkt.get("user_data", {})
                            user = User.from_wire_dict(ud)
                            if _verify(user.canonical_bytes(),
                                       pkt.get("signature", ""),
                                       user.public_key):
                                self.callbacks.on_user_received(user)
                                counts["users"] += 1
                            continue

                        TYPE_MAP = {
                            "expense":    (Expense,    "expenses"),
                            "settlement": (Settlement, "settlements"),
                            "comment":    (UserComment,"comments"),
                            "split":      (Split,      "splits"),
                            "attachment": (Attachment, "attachments"),
                        }
                        if ptype in TYPE_MAP:
                            cls, key = TYPE_MAP[ptype]
                            rec = self._decrypt_and_verify(
                                pkt["data"], cls)
                            if rec:
                                dispatch = {
                                    "expense":    self.callbacks.on_expense_received,
                                    "settlement": self.callbacks.on_settlement_received,
                                    "comment":    self.callbacks.on_comment_received,
                                    "split":      self.callbacks.on_split_received,
                                    "attachment": self.callbacks.on_attachment_received,
                                }[ptype]
                                dispatch(rec)
                                counts[key] += 1

                    except Exception as e:
                        logger.warning("History parse error: %s", e)

            self.callbacks.on_history_synced(counts)
            logger.info("History: +%s from %s", counts, peer_id_str[:12])

        except Exception as e:
            logger.error("History request error from %s: %s",
                         peer_id_str[:12], e)
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Push delta back to server
    # ------------------------------------------------------------------

    async def _push_delta(self, peer_id_str: str, server_map: dict) -> None:
        """
        After history sync the server sends its lamport map.
        We compute what the server is missing and push it back via GossipSub.
        """
        import trio
        from storage import get_records_unknown_to

        if not self._db:
            return

        delta = get_records_unknown_to(self._db, server_map, self._group_id)
        to_push: list[bytes] = []

        type_map = [
            ("expense",    "expenses"),
            ("settlement", "settlements"),
            ("comment",    "comments"),
            ("split",      "splits"),
            ("attachment", "attachments"),
        ]

        for ptype, key in type_map:
            for row in delta.get(key, []):
                blob = self._row_to_wire(row, ptype)
                if blob is None:
                    continue
                extra: dict = {}
                if ptype in ("comment", "split", "attachment"):
                    extra["belongs_to"] = row["belongs_to"]
                pkt = json.dumps({
                    "type":      ptype,
                    "id":        row["id"],
                    "timestamp": row["timestamp"],
                    "data":      blob.hex(),
                    **extra,
                }).encode()
                to_push.append(pkt)

        for row in delta.get("users", []):
            d = dict(row)
            pkt = json.dumps({
                "type":      "user",
                "id":        f"{d['public_key']}:{d['group_id']}",
                "timestamp": d["timestamp"],
                "user_data": d,
                "signature": d["signature"],
            }).encode()
            to_push.append(pkt)

        if not to_push:
            logger.debug("Delta push: server %s already up to date",
                         peer_id_str[:12])
            return

        for pkt in to_push:
            try:
                await self._pubsub.publish(self.topic_id, pkt)
                await trio.sleep(0.05)
            except Exception as e:
                logger.warning("Delta push error: %s", e)

        logger.info("Delta push: sent %d records to %s",
                    len(to_push), peer_id_str[:12])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_file(self, sha256: str) -> None:
        if self._running:
            self._cmd_queue.put({"cmd": "req_file", "sha256": sha256})

    def request_history_from_all(self) -> None:
        if self._running:
            self._cmd_queue.put({"cmd": "req_history_all"})

    def connect_to_peer(self, multiaddr_str: str) -> None:
        if self._running:
            self._cmd_queue.put({"cmd": "connect", "addr": multiaddr_str})

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
