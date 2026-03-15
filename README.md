# SplitP2P

Decentralized expense splitting — no server, no account, no internet required.

Expenses are stored locally, automatically synchronized between peers over P2P,
file attachments transferred peer-to-peer, and debts minimized automatically.

---

## Features

### Core
- **Multiple isolated groups** — each group has its own password and random salt;
  peers from other groups cannot read anything even if they share the same network
- **P2P synchronization** — expenses distributed via GossipSub to all group peers;
  CRDT with Lamport clocks prevents conflicts even under clock drift
- **Expense tracking** — description, amount, payer, date, category, notes
- **Split modes** — equal, custom amounts, or percentage (e.g. 30% / 70%)
- **Currency conversion** — enter in any of 24 currencies, auto-converted to the
  group currency; rates cached locally, refreshed with random jitter
- **File attachments** — images (JPG, PNG, GIF, WEBP) and PDFs; transferred
  peer-to-peer, integrity verified by SHA-256
- **Debt minimization** — greedy algorithm computes the minimum number of transfers
- **Recorded settlements** — mark debts as paid; one-click from the open debts list
- **Full offline support** — all features work without network; sync happens
  automatically once peers are reachable

### Search & Analytics
- **Live search + filters** — full-text search across description, category and notes;
  filter by category and by member; result count shown inline
- **Charts** — expenses by category, balance per person, cumulative expenses over
  time, balance history per person (all four in one window, PNG export)
- **Export** — CSV (no dependencies) and PDF (`fpdf2`); both include a
  **% of total** column and a per-person balance summary showing each
  person's share of group spending

### P2P Network
- **mDNS** — automatic discovery on the local network (no configuration needed)
- **IPFS bootstrap nodes** — connects to public libp2p nodes for internet-wide discovery
- **AutoNAT** — detects whether we are behind a NAT/firewall
- **Circuit Relay v2** — connections via public relay nodes when behind NAT
- **Kademlia DHT** — advertises the group topic ID in the global DHT so members
  can find each other without being in the same room
- **Initial history sync** — when a new peer connects, it automatically requests all
  records it has not seen yet (delta sync)
- **Retry with backoff** — file downloads retry up to 3 times (1 s, 3 s, 7 s) and
  clean up `.tmp` files on failure; stale `.tmp` files are also removed at startup

### Security
- **AES-256-GCM** encryption for all group data; key derived via PBKDF2-HMAC-SHA256
  (600,000 iterations) from password + random 16-byte salt
- **Ed25519 signatures** on every expense and settlement (authenticity)
- **Creator-only editing** — only the original creator can edit or delete their
  expenses; enforced both in the UI and cryptographically in the network layer
- **Signature verification** before any blob reaches the database or UI
- **QR code onboarding** — group password, salt and currency packed into a
  compact (~140 char) base64-JSON payload; scan once to join instantly
- **Tombstone sync** — deletions propagate to all peers; attachment files are
  removed once unreferenced, but the DB tombstone persists for sync

### CRDT
Three-level merge priority (robust against clock drift):

1. **Lamport clock** — causality-based, clock-drift-independent;
   restored from DB on startup so new entries always win over old ones
2. **Wall clock** — tiebreaker when Lamport values are equal
3. **author_pubkey** — deterministic final tiebreaker (lexicographic);
   both sides reach the same result without communication — no split-brain

---

## Requirements

- Python 3.11 or newer  
  (3.12 recommended; `libp2p` does not yet build on 3.14)
- Tkinter — usually pre-installed; on Debian/Ubuntu:
  ```
  sudo apt install python3-tk
  ```

---

## Installation

```bash
git clone <repo-url>
cd splitp2p
pip install -r requirements.txt
python main.py
```

On first start you will be asked for a display name and a storage location.
An Ed25519 key pair is generated automatically and stored at:

- Linux/macOS: `~/.config/SplitP2P/config.json`
- Windows: `%LOCALAPPDATA%\SplitP2P\config.json`

---

## Quick start

1. Enter your **display name** (first start only)
2. Choose a **storage location** for the database and attachments
3. Click **Create / Join** — enter a group name, shared password, and currency;
   everything is saved and never asked again
4. Show the **QR code** (`📤 Show QR`) and have other members scan it
   with `📥 Import QR` to join
5. Add members via **+ Member** (name + their public key, or generate a temporary one)
6. Add expenses via **+ Expense** — saved locally and broadcast to connected peers
7. The **Open debts** sidebar shows who owes whom; click **✓ paid** to record settlements
8. Use **📊 Charts** for visual analysis and **⬇ Export** for CSV/PDF

---

## Architecture

```
main.py              Entry point, logging
gui.py               Tkinter UI (2,900+ lines)
├── QRShowDialog          Display group QR code
├── QRImportDialog        Scan / paste QR to join a group
├── GroupSelectDialog     Pick from known groups
├── NewGroupDialog        Create / join (password entered once)
├── ExpenseDialog         Add / edit expense (live currency preview, % split)
├── SettlementDialog      Record a payment
├── ChartsWindow          Four charts + PNG export
├── ExportDialog          CSV / PDF with % of total + balance summary
├── ActivityLogWindow     Chronological change log + live P2P events
└── AttachmentViewer      Image / PDF preview

network.py           P2P layer (libp2p + trio)
├── P2PNetwork            Host, GossipSub, mDNS, bootstrap, NAT traversal
├── _verify_and_decode_blob  Decrypt + signature check before any callback
├── _download_file        Retry with exponential backoff + .tmp cleanup
├── _cleanup_stale_tmp    Startup cleanup of incomplete downloads
└── NetworkCallbacks      Thread-safe bridge to Tkinter (via root.after)

models.py            Data models (dataclasses, JSON-serializable)
├── Expense               lamport_clock, Ed25519 signature, AES-GCM blob
├── RecordedSettlement    Signed + CRDT-synced payment record
├── Member, Attachment, Split

ledger.py            Debt calculation + caching
├── ledger_cache_key()    Fast cache key — avoids redundant recalculation
├── compute_balances()    Net balance per person
└── compute_settlements() Greedy debt minimization

crypto.py            Cryptography
├── PBKDF2 + AES-256-GCM  Group encryption / decryption
├── Ed25519               Sign / verify expenses and settlements
└── group_topic_id()      SHA256(salt)[:16] — P2P routing identifier

currency.py          Exchange rates
├── fetch_rates_online()  open.er-api.com (fallback: exchangerate-api.com)
├── get_rates()           Cache-or-online with jitter
└── convert()             Via base currency

storage.py           SQLite persistence
├── _wins_over()          CRDT merge decision
├── get_max_lamport_clock()  Restore Lamport state across restarts
├── delete_attachment_if_unreferenced()
└── load_all_*_since()   Delta sync helpers for network.py

config_manager.py    JSON settings (platform-specific path)
```

---

## P2P protocol

### GossipSub topic

```
"splitp2p-" + SHA256(group_salt)[:16]
```

The topic ID is derived from the random group salt — not from the password —
so it reveals nothing about the group even to passive observers.

### Packet types

```json
{ "type": "expense",    "id": "<uuid>", "timestamp": 1710426000, "blob": "<hex>" }
{ "type": "settlement", "id": "<uuid>", "timestamp": 1710426001, "blob": "<hex>" }
{ "type": "member",     "pubkey": "<hex>", "data": {"display_name": "Ecki"} }
```

Every blob is AES-256-GCM encrypted. Verification (decrypt + Ed25519 check)
happens in `_verify_and_decode_blob()` before any callback fires.

### File transfer  `/splitp2p/files/1.0`

```
-> SHA-256 hex  (request)
<- binary data  (response in 16 KB chunks)
```

SHA-256 verified after download; retried up to 3× on failure.

### History sync  `/splitp2p/history/1.0`

Triggered automatically on every new peer connection:

```
-> {"since_ts": <int>, "topic": "<topic_id>"}
<- {"type": "expense",    "id": "...", "blob": "<hex>"}\n
   {"type": "settlement", "id": "...", "blob": "<hex>"}\n
   \n   <- EOF marker
```

### QR code payload

```json
{"v":1,"name":"IslandTrip","pw":"secret","salt":"99cafd53...","currency":"ISK"}
```

Base64-encoded, ~140 characters. Version field (`v`) allows future format changes.

---

## Security model

| Layer | Mechanism | Protects against |
|-------|-----------|-----------------|
| Confidentiality | AES-256-GCM (PBKDF2 key) | non-members reading data |
| Authenticity | Ed25519 signatures | tampered or forged entries |
| Creator integrity | payer_pubkey immutable in sig | impersonation edits |
| Routing isolation | SHA256(salt) topic | group metadata leakage |
| Attachment integrity | SHA-256 in expense signature | attachment swap |
| Clock drift | Lamport clock CRDT | wrong timestamps winning merges |

---

## Dependencies

| Package | Purpose | Required |
|---------|---------|---------|
| `cryptography` | Ed25519, AES-256-GCM | yes |
| `libp2p` | P2P sync | recommended |
| `multiaddr` | Parse IPFS bootstrap addresses | recommended |
| `trio` | Async backend for libp2p | recommended |
| `Pillow` | In-app image preview | optional |
| `matplotlib` | Charts window | optional |
| `fpdf2` | PDF export | optional |
| `qrcode[pil]` | QR code image display | optional |
| `opencv-python` | QR camera / file scan | optional |

All optional packages degrade gracefully — the app runs without them,
affected features show an install hint instead.

---

## Roadmap: Kotlin / Android

This Python prototype is the reference implementation for a future Android app.

| Component | Python prototype | Android target |
|-----------|-----------------|----------------|
| UI | Tkinter | Jetpack Compose |
| Database | SQLite (stdlib) | Room |
| Async | trio | Kotlin Coroutines |
| Key storage | config.json | Android Keystore |
| Local transport | libp2p mDNS | Nearby Connections API |
| Internet transport | libp2p + IPFS | jvm-libp2p |
| HTTP | urllib | Ktor |

CRDT logic, PBKDF2 key derivation, Ed25519 signatures, debt calculation and
QR payload format are directly portable — same algorithms, fully interoperable.

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
