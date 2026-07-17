# SplitP2P

A prototype for splitting shared expenses on a group trip without a
central server: each device runs a local libp2p node, expenses/settlements
sync over GossipSub, and a 32-byte group key (shared via QR code) both
encrypts the data and identifies the group.

Built as a Python/Tkinter desktop app. A Kotlin/Android port is a stated
goal, not something that exists yet — see [Kotlin/Android Roadmap](#kotlinandroid-roadmap).

**Status:** working prototype, exercised through a pytest suite covering the
core logic (ledger, models, crypto, storage, currency) and the GUI dialogs
that were easiest to get wrong. Real two-peer P2P connectivity (mDNS
discovery, GossipSub mesh) has not been verified end-to-end — see
[Known issues](#known-issues) before relying on it.

---

## Quick start

```bash
python -m venv venv && source venv/bin/activate
pip install -e .
python main.py
```

**tkinter** is required but not pip-installable on some distros:
```bash
sudo apt install python3-tk   # Debian/Ubuntu
sudo pacman -S tk             # Arch/CachyOS
```

Dependencies are declared in `pyproject.toml` (`[project.dependencies]`) —
there's no `requirements.txt`.

### Development setup

```bash
pip install -e ".[dev]"
pre-commit install   # runs ruff + mypy + pytest on every commit
```

Ruff and mypy are configured in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`).
To run everything the pre-commit hook runs, manually:

```bash
ruff check . && ruff format --check .
mypy .
pytest
```

The same four checks run in CI on every push/PR to `main`
(`.github/workflows/ci.yml`) — not yet verified end-to-end on an actual
GitHub Actions runner, since tkinter availability there is a known rough
edge (see the workflow's comments).

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  gui.py         Tkinter UI + App logic          │
│  models.py      Expense, Settlement, Comment    │
│  ledger.py      Debt calculation (integer)      │
│  crypto.py      Ed25519 + SecretBox (pynacl)    │
│  storage.py     SQLite + CRDT merge             │
│  network.py     libp2p GossipSub + delta sync   │
│  currency.py    Exchange rate fetching          │
│  config_manager.py  JSON config, platform paths │
└─────────────────────────────────────────────────┘
```

### No server, no account

- Each device runs a full libp2p node
- mDNS for local network discovery (no router config needed)
- GossipSub for real-time sync
- Delta history sync on peer connect (Lamport-clock based)
- SQLite as local CRDT store — last-writer-wins with Lamport clocks

### Amounts

All amounts are stored as integers in the **smallest currency unit**
(cents for EUR/USD, yen for JPY). The GUI converts user-entered decimal
amounts via `to_minor()` before they're saved, and back via `from_minor()`
when displaying or editing them.

Conversion helpers in `models.py`:
```python
to_minor(12.50, "EUR")    # → 1250
from_minor(1250, "EUR")   # → 12.5
format_amount(1250, "EUR") # → "12.50"
```

---

## Wire Format 1.0

### QR Code Payload (v3)

Members join a group by scanning a QR code. The payload is
base64-encoded JSON:

```json
{
  "v":        3,
  "name":     "IslandTrip",
  "key":      "a3f1...64 hex chars...9b2e",
  "topic":    "550e8400-e29b-41d4-a716-446655440000",
  "currency": "EUR"
}
```

| Field      | Type   | Description |
|------------|--------|-------------|
| `v`        | int    | Payload version — must be `3` |
| `name`     | string | Human-readable group name |
| `key`      | string | 32-byte SecretBox key as 64 hex chars |
| `topic`    | string | UUID v4 — P2P routing topic, not secret |
| `currency` | string | ISO 4217 currency code (e.g. `"EUR"`) |

The `key` is the only secret. The `topic` UUID is used to identify
the group in the P2P mesh (`splitp2p-{topic}` as GossipSub topic string)
and can be logged/shared safely.

### GossipSub Packets

All packets are published to topic `splitp2p-{topic-uuid}` as UTF-8 JSON.
Expense/settlement/comment/split/attachment records are SecretBox-encrypted
before publishing; the encrypted blob is hex-encoded into the `data` field.

**Expense / Settlement / Comment / Split / Attachment:**
```json
{
  "type":      "expense",
  "id":        "uuid",
  "timestamp": 1712345678,
  "data":      "hex-encoded encrypted record"
}
```
`type` is one of `expense`, `settlement`, `comment`, `split`, `attachment`.

**User announce (identity):**
```json
{
  "type":      "user",
  "user_data": { "public_key": "...", "name": "Alice", "group_id": "...",
                 "timestamp": 1712345678, "lamport_clock": 3, "signature": "" },
  "signature": "Ed25519 signature over user_data's canonical bytes"
}
```

User packets are **not encrypted** — display names are visible to anyone
who knows the topic UUID. Everything else requires the group key to decrypt.

### History Sync Protocol (v1.0)

Stream protocol on `/splitp2p/history/1.0`.
Triggered on peer connect — bidirectional delta sync.

**Step 1 — Client → Server (request):**
```json
{
  "topic": "splitp2p-{uuid}",
  "known": {
    "expenses":    {"<id>": <lamport_clock>, ...},
    "settlements": {"<id>": <lamport_clock>, ...},
    "comments":    {"<id>": <lamport_clock>, ...},
    "splits":      {"<id>": <lamport_clock>, ...},
    "attachments": {"<id>": <lamport_clock>, ...},
    "users":       {"<pubkey>:<group_id>": <lamport_clock>, ...}
  }
}
```

The client sends its complete Lamport clock map. The server sends back
only records the client does not have, or has an older version of.

**Step 2 — Server → Client (response):**

Line-delimited JSON packets, one per record (same shapes as the GossipSub
packets above):
```
{"type":"expense","id":"...","data":"hex"}
{"type":"settlement","id":"...","data":"hex"}
{"type":"lamport_map","map":{"expenses":{...},"settlements":{...},...}}

```

The `lamport_map` packet contains the server's own state. The client
uses this to push back any records the server is missing (via GossipSub).
A blank line signals end of stream.

**Step 3 — Client → Server (push-back):**

Records the server is missing are pushed via GossipSub broadcast
(not a direct stream) with a small delay between packets.

### File Transfer Protocol

Binary stream protocol on `/splitp2p/files/1.0`.

**Request:** client sends the 64-char hex SHA-256 of the file.

**Response:** server sends encrypted chunks, then an EOF sentinel:
```
[4-byte big-endian length][nonce(24) + ciphertext + MAC(16)]
[4-byte big-endian length][nonce(24) + ciphertext + MAC(16)]
...
\x00\x00\x00\x00   ← EOF sentinel (length = 0)
```

Each chunk is individually encrypted with SecretBox using the group key.
The SHA-256 of the decrypted file is verified against the requested hash.

### Encrypted Blob Format

SecretBox (XSalsa20-Poly1305) output:
```
[nonce: 24 bytes][ciphertext][MAC: 16 bytes]
```

The nonce is randomly generated per encryption. The blob is opaque —
without the 32-byte group key, neither content nor plaintext length
can be determined.

### Signatures

Every expense, settlement, split, comment, attachment, and user record is
signed with the author's Ed25519 private key. Each model's `canonical_bytes()`
method returns a deterministic byte representation of its synced fields
(local-only fields, e.g. `Attachment.is_stored`, are excluded) for signing.
The signature is stored inside the encrypted blob for most record types;
user records are signed but sent in the clear (see above).

---

## Cryptography

| Primitive       | Algorithm              | Library  | Purpose |
|-----------------|------------------------|----------|---------|
| Signing         | Ed25519                | pynacl   | Author authentication |
| Encryption      | XSalsa20-Poly1305      | pynacl   | Group data confidentiality |
| Key             | 32 random bytes        | pynacl   | SecretBox key |
| Transport       | Noise (XX pattern)     | libp2p   | P2P connection security |
| File hash       | SHA-256                | stdlib   | Attachment integrity |

No passwords, no KDF. The 32-byte group key is the secret —
generated once at group creation, shared via QR code.

The libp2p Noise transport provides an additional encryption layer
for all P2P connections — the SecretBox layer encrypts at rest and
ensures only group members can read the data regardless of transport.

⚠️ **The user's own Ed25519 private key is stored unencrypted.**
`config_manager.py` writes it as plain hex (`private_key_hex`) into
`config.json` in the OS config directory (e.g. `~/.config/SplitP2P/config.json`
on Linux) with no OS keychain integration and no passphrase. Anyone with
filesystem read access to that file can impersonate the user's identity
in any group they're a member of. This is separate from the group key
(which is meant to be shared) — it's the per-device signing key, and it
currently has no protection at rest.

---

## CRDT Merge

Concurrent edits are resolved with three-level priority (`storage._wins`):

1. **Lamport clock** — higher wins
2. **Timestamp** — higher wins (tiebreak)
3. **Author pubkey** — lexicographically higher wins (deterministic tiebreak)

Deletes are implemented as tombstones (`is_deleted = 1`) and win or lose
against other writes using the exact same three-level comparison — a
tombstone is not automatically prioritized, it just competes as a normal
write with whatever Lamport clock it carries.

---

## Known issues

- **P2P sync between two devices is not end-to-end tested.** The libp2p
  version this project actually installs (0.6.0) is a large jump from what
  used to be pinned (`>=0.1.5`), with breaking API changes (`GossipSub()`
  argument requirements, `IHost.run()` and `Pubsub.run()` both becoming
  async context managers that must be driven via
  `libp2p.tools.async_service.background_trio_service`, not called
  directly). A single running instance has been smoke-tested end-to-end
  (host starts, listens, discovers and connects to real peers via mDNS and
  bootstrap), which caught and fixed two crash bugs that made the P2P
  thread fail immediately on every previous run. Full two-device GossipSub
  sync (actually exchanging expenses/settlements) has still not been
  exercised in this environment — test with two real instances before
  trusting sync in practice.
- Camera QR scanning depends on `opencv-python`; if it's not installed the
  "Scan camera" button is simply hidden (falls back to image-file import or
  pasting the base64 text).
- `AddMemberDialog` (gui.py) is defined but has no call site anywhere in the
  app — there's no menu item or button that opens it. Its own logic is
  tested in isolation, but it's not reachable from the running UI.

