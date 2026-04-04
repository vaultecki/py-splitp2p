# SplitP2P

Decentralized, serverless expense splitting for group trips.  
No account. No cloud. Members join via QR code.

Built as a Python/Tkinter prototype — the target platform is Kotlin/Android.

---

## Quick start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

**tkinter** is required but not pip-installable on some distros:
```bash
sudo apt install python3-tk   # Debian/Ubuntu
sudo pacman -S tk             # Arch/CachyOS
```

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
(cents for EUR/USD, yen for JPY). No float rounding errors.

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
Expense/settlement/comment blobs are SecretBox-encrypted before publishing.

**Expense:**
```json
{
  "type":      "expense",
  "id":        "uuid",
  "timestamp": 1712345678,
  "blob":      "hex-encoded encrypted expense"
}
```

**Settlement:**
```json
{
  "type":      "settlement",
  "id":        "uuid",
  "timestamp": 1712345678,
  "blob":      "hex-encoded encrypted settlement"
}
```

**Comment:**
```json
{
  "type":       "comment",
  "id":         "uuid",
  "expense_id": "uuid",
  "timestamp":  1712345678,
  "blob":       "hex-encoded encrypted comment"
}
```

**Member announce:**
```json
{
  "type":   "member",
  "pubkey": "64 hex chars (Ed25519 verify key)",
  "data":   {
    "display_name": "Alice",
    "joined_at":    1712345678
  }
}
```

Member packets are **not encrypted** — display names are visible to anyone
who knows the topic UUID. The expense/settlement/comment content requires the
group key to decrypt.

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
    "comments":    {"<id>": <lamport_clock>, ...}
  }
}
```

The client sends its complete Lamport clock map. The server sends back
only records the client does not have, or has an older version of.

**Step 2 — Server → Client (response):**

Line-delimited JSON packets, one per record:
```
{"type":"expense","id":"...","blob":"hex"}\n
{"type":"settlement","id":"...","blob":"hex"}\n
{"type":"lamport_map","map":{"expenses":{...},"settlements":{...},"comments":{...}}}\n
\n
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

Every expense, settlement, and comment is signed with the author's
Ed25519 private key before encryption. The `canonical_bytes()` method
on each model returns a deterministic byte representation for signing:

```python
# Example (Expense.canonical_bytes):
f"{id}|{description}|{amount}|{currency}|{payer_pubkey}|{timestamp}".encode()
```

The signature is stored inside the encrypted blob, not on the wire.
The receiving peer decrypts first, then verifies the signature.

---

## Cryptography

| Primitive       | Algorithm              | Library  | Purpose |
|-----------------|------------------------|----------|---------|
| Signing         | Ed25519                | pynacl   | Author authentication |
| Encryption      | XSalsa20-Poly1305      | pynacl   | Group data confidentiality |
| Key             | 32 random bytes        | pynacl   | SecretBox key |
| Transport       | Noise (XX pattern)     | libp2p   | P2P connection security |
| File hash       | SHA-256                | stdlib   | Attachment integrity |

No passwords. No KDF. The 32-byte group key is the secret —
generated once at group creation, shared via QR code.

The libp2p Noise transport provides an additional encryption layer
for all P2P connections — the SecretBox layer encrypts at rest and
ensures only group members can read the data regardless of transport.

---

## CRDT Merge

Concurrent edits are resolved with three-level priority:

1. **Lamport clock** — higher wins
2. **Timestamp** — higher wins (tiebreak)
3. **Author pubkey** — lexicographically higher wins (deterministic tiebreak)

Deletes are implemented as tombstones (`is_deleted = True`) and always
win over non-deleted records with the same or lower Lamport clock.

---

## Kotlin/Android Roadmap

The wire format is stable. Key portability notes:

| Component       | Python           | Kotlin/Android         |
|-----------------|------------------|------------------------|
| SecretBox       | pynacl           | lazysodium             |
| Ed25519         | pynacl           | lazysodium             |
| P2P transport   | libp2p (py)      | Nearby Connections API |
| Local DB        | SQLite3          | Room                   |
| UI              | Tkinter          | Jetpack Compose        |
| QR scan         | opencv-python    | ML Kit / ZXing         |

The QR v3 payload, GossipSub packet types, history sync protocol,
file transfer protocol, and CRDT merge logic port directly.
