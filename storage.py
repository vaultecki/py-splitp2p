# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
storage.py — SQLite persistence layer

Schema design:
  - Fully normalized, no blobs. Encryption lives above this layer.
  - group_id on every synced table — supports multiple groups per device.
  - Lamport clocks + author_pubkey on every synced record for CRDT merge.
  - Local-only fields (is_stored, group_info, comments_system) are never
    included in canonical_bytes() / signatures / network sync.
  - group_info: written once from QR code, never synced, never modified.

Sync status:
  group_info       local-only
  users            synced
  expenses         synced
  split            synced (child of expense, no is_deleted)
  settlements      synced
  comments_user    synced
  comments_system  local-only
  attachments      synced (is_stored is local-only)
  exchange_rates   local-only
"""

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

DB_PATH     = ""
STORAGE_DIR = ""


_DDL = """
CREATE TABLE IF NOT EXISTS group_info (
    group_id  TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    currency  TEXT NOT NULL,
    group_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    public_key    TEXT    NOT NULL,
    group_id      TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    timestamp     INTEGER NOT NULL DEFAULT 0,
    lamport_clock INTEGER NOT NULL DEFAULT 0,
    signature     TEXT    NOT NULL,
    PRIMARY KEY (public_key, group_id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id                TEXT    PRIMARY KEY,
    group_id          TEXT    NOT NULL,
    timestamp         INTEGER NOT NULL,
    expense_date      INTEGER NOT NULL DEFAULT 0,
    lamport_clock     INTEGER NOT NULL DEFAULT 0,
    author_pubkey     TEXT    NOT NULL,
    is_deleted        INTEGER NOT NULL DEFAULT 0,
    amount            INTEGER NOT NULL DEFAULT 0,
    description       TEXT,
    category          TEXT,
    original_amount   INTEGER,
    original_currency TEXT,
    signature         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS split (
    id            TEXT    PRIMARY KEY,
    belongs_to    TEXT    NOT NULL,
    timestamp     INTEGER NOT NULL,
    lamport_clock INTEGER NOT NULL DEFAULT 0,
    author_pubkey TEXT    NOT NULL,
    payer_key     TEXT    NOT NULL,
    debtor_key    TEXT    NOT NULL,
    amount        INTEGER NOT NULL DEFAULT 0,
    signature     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS settlements (
    id            TEXT    PRIMARY KEY,
    group_id      TEXT    NOT NULL,
    timestamp     INTEGER NOT NULL,
    lamport_clock INTEGER NOT NULL DEFAULT 0,
    author_pubkey TEXT    NOT NULL,
    is_deleted    INTEGER NOT NULL DEFAULT 0,
    from_key      TEXT    NOT NULL,
    to_key        TEXT    NOT NULL,
    amount        INTEGER NOT NULL DEFAULT 0,
    signature     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS comments_user (
    id            TEXT    PRIMARY KEY,
    belongs_to    TEXT    NOT NULL,
    timestamp     INTEGER NOT NULL,
    lamport_clock INTEGER NOT NULL DEFAULT 0,
    author_pubkey TEXT    NOT NULL,
    is_deleted    INTEGER NOT NULL DEFAULT 0,
    comment       TEXT,
    signature     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS comments_system (
    id         TEXT    PRIMARY KEY,
    belongs_to TEXT    NOT NULL,
    timestamp  INTEGER NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    comment    TEXT
);

CREATE TABLE IF NOT EXISTS attachments (
    id            TEXT    PRIMARY KEY,
    belongs_to    TEXT    NOT NULL,
    timestamp     INTEGER NOT NULL,
    lamport_clock INTEGER NOT NULL DEFAULT 0,
    author_pubkey TEXT    NOT NULL,
    sha256        TEXT    NOT NULL,
    filename      TEXT    NOT NULL,
    mime          TEXT,
    size          INTEGER,
    is_stored     INTEGER NOT NULL DEFAULT 0,
    signature     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    base        TEXT    NOT NULL,
    target      TEXT    NOT NULL,
    rate        REAL    NOT NULL,
    fetched_at  INTEGER NOT NULL,
    PRIMARY KEY (base, target)
);

CREATE INDEX IF NOT EXISTS idx_expenses_group    ON expenses(group_id, is_deleted, expense_date);
CREATE INDEX IF NOT EXISTS idx_expenses_lamport  ON expenses(group_id, lamport_clock);
CREATE INDEX IF NOT EXISTS idx_split_belongs     ON split(belongs_to);
CREATE INDEX IF NOT EXISTS idx_settlements_group ON settlements(group_id, is_deleted);
CREATE INDEX IF NOT EXISTS idx_comments_belongs  ON comments_user(belongs_to, is_deleted);
CREATE INDEX IF NOT EXISTS idx_attach_belongs    ON attachments(belongs_to);
CREATE INDEX IF NOT EXISTS idx_attach_sha256     ON attachments(sha256);
CREATE INDEX IF NOT EXISTS idx_users_group       ON users(group_id);
"""


def set_paths(db_path: str, storage_dir: str) -> None:
    global DB_PATH, STORAGE_DIR
    DB_PATH     = db_path
    STORAGE_DIR = storage_dir
    os.makedirs(storage_dir, exist_ok=True)
    logger.info("Paths set: db=%s  storage=%s", db_path, storage_dir)


def init_db(db_path: str = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_DDL)
    conn.commit()
    logger.info("DB ready: %s", path)
    return conn


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


# ---------------------------------------------------------------------------
# group_info — local-only
# ---------------------------------------------------------------------------

def save_group_info(db: sqlite3.Connection, group_id: str, name: str,
                    currency: str, group_key: bytes) -> None:
    db.execute(
        "INSERT OR IGNORE INTO group_info(group_id,name,currency,group_key)"
        " VALUES(?,?,?,?)",
        (group_id, name, currency, group_key.hex()))
    db.commit()


def get_group_info(db: sqlite3.Connection,
                   group_id: str) -> Optional[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM group_info WHERE group_id=?", (group_id,)).fetchone()


def get_group_key(db: sqlite3.Connection, group_id: str) -> Optional[bytes]:
    row = db.execute(
        "SELECT group_key FROM group_info WHERE group_id=?",
        (group_id,)).fetchone()
    return bytes.fromhex(row["group_key"]) if row else None


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------

def save_user(db: sqlite3.Connection, *, group_id: str, public_key: str,
              name: str, timestamp: int, lamport_clock: int,
              signature: str) -> bool:
    ex = db.execute(
        "SELECT lamport_clock,timestamp FROM users"
        " WHERE public_key=? AND group_id=?",
        (public_key, group_id)).fetchone()
    if ex and not _wins(lamport_clock, timestamp,
                        ex["lamport_clock"], ex["timestamp"]):
        return False
    if ex:
        db.execute(
            "UPDATE users SET name=?,timestamp=?,lamport_clock=?,"
            "signature=? WHERE public_key=? AND group_id=?",
            (name, timestamp, lamport_clock, signature,
             public_key, group_id))
    else:
        db.execute(
            "INSERT INTO users(public_key,name,timestamp,group_id,"
            "lamport_clock,signature) VALUES(?,?,?,?,?,?)",
            (public_key, name, timestamp, group_id, lamport_clock, signature))
    db.commit()
    return True


def get_user(db: sqlite3.Connection,
             public_key: str,
             group_id: str = "") -> Optional[sqlite3.Row]:
    """group_id required for composite PK lookup."""
    return db.execute(
        "SELECT * FROM users WHERE public_key=? AND group_id=?",
        (public_key, group_id)).fetchone()


def get_all_users(db: sqlite3.Connection,
                  group_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM users WHERE group_id=? ORDER BY name",
        (group_id,)).fetchall()


# ---------------------------------------------------------------------------
# expenses
# ---------------------------------------------------------------------------

def save_expense(db: sqlite3.Connection, *, id: str, group_id: str,
                 timestamp: int, expense_date: int, lamport_clock: int,
                 author_pubkey: str, is_deleted: int = 0, amount: int,
                 description: str = None, category: str = None,
                 original_amount: int = None, original_currency: str = None,
                 signature: str) -> bool:
    ex = db.execute(
        "SELECT lamport_clock,timestamp,author_pubkey FROM expenses"
        " WHERE id=?", (id,)).fetchone()
    if ex and not _wins(lamport_clock, timestamp,
                        ex["lamport_clock"], ex["timestamp"],
                        author_pubkey, ex["author_pubkey"]):
        return False
    if ex:
        db.execute(
            "UPDATE expenses SET timestamp=?,expense_date=?,lamport_clock=?,"
            "author_pubkey=?,is_deleted=?,amount=?,description=?,category=?,"
            "original_amount=?,original_currency=?,signature=? WHERE id=?",
            (timestamp, expense_date, lamport_clock, author_pubkey, is_deleted,
             amount, description, category, original_amount, original_currency,
             signature, id))
    else:
        db.execute(
            "INSERT INTO expenses(id,group_id,timestamp,expense_date,"
            "lamport_clock,author_pubkey,is_deleted,amount,description,"
            "category,original_amount,original_currency,signature)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (id, group_id, timestamp, expense_date, lamport_clock,
             author_pubkey, is_deleted, amount, description, category,
             original_amount, original_currency, signature))
    db.commit()
    return True


def get_expenses(db: sqlite3.Connection, group_id: str,
                 include_deleted: bool = False) -> list[sqlite3.Row]:
    q = ("SELECT * FROM expenses WHERE group_id=?"
         + ("" if include_deleted else " AND is_deleted=0")
         + " ORDER BY expense_date DESC, timestamp DESC")
    return db.execute(q, (group_id,)).fetchall()


def get_expense(db: sqlite3.Connection, id: str) -> Optional[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM expenses WHERE id=?", (id,)).fetchone()


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------

def save_splits(db: sqlite3.Connection, expense_id: str,
                splits: list[dict]) -> None:
    """Replace all splits for an expense atomically."""
    db.execute("DELETE FROM split WHERE belongs_to=?", (expense_id,))
    for s in splits:
        db.execute(
            "INSERT INTO split(id,belongs_to,timestamp,lamport_clock,"
            "author_pubkey,payer_key,debtor_key,amount,signature)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (s["id"], expense_id, s["timestamp"], s["lamport_clock"],
             s["author_pubkey"], s["payer_key"], s["debtor_key"],
             s["amount"], s["signature"]))
    db.commit()


def get_splits(db: sqlite3.Connection,
               expense_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM split WHERE belongs_to=?", (expense_id,)).fetchall()


# ---------------------------------------------------------------------------
# settlements
# ---------------------------------------------------------------------------

def save_settlement(db: sqlite3.Connection, *, id: str, group_id: str,
                    timestamp: int, lamport_clock: int, author_pubkey: str,
                    is_deleted: int = 0, from_key: str, to_key: str,
                    amount: int, signature: str) -> bool:
    ex = db.execute(
        "SELECT lamport_clock,timestamp,author_pubkey FROM settlements"
        " WHERE id=?", (id,)).fetchone()
    if ex and not _wins(lamport_clock, timestamp,
                        ex["lamport_clock"], ex["timestamp"],
                        author_pubkey, ex["author_pubkey"]):
        return False
    if ex:
        db.execute(
            "UPDATE settlements SET timestamp=?,lamport_clock=?,"
            "author_pubkey=?,is_deleted=?,from_key=?,to_key=?,"
            "amount=?,signature=? WHERE id=?",
            (timestamp, lamport_clock, author_pubkey, is_deleted,
             from_key, to_key, amount, signature, id))
    else:
        db.execute(
            "INSERT INTO settlements(id,group_id,timestamp,lamport_clock,"
            "author_pubkey,is_deleted,from_key,to_key,amount,signature)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (id, group_id, timestamp, lamport_clock, author_pubkey,
             is_deleted, from_key, to_key, amount, signature))
    db.commit()
    return True


def get_settlements(db: sqlite3.Connection, group_id: str,
                    include_deleted: bool = False) -> list[sqlite3.Row]:
    q = ("SELECT * FROM settlements WHERE group_id=?"
         + ("" if include_deleted else " AND is_deleted=0")
         + " ORDER BY timestamp DESC")
    return db.execute(q, (group_id,)).fetchall()


# ---------------------------------------------------------------------------
# comments
# ---------------------------------------------------------------------------

def save_comment_user(db: sqlite3.Connection, *, id: str, belongs_to: str,
                      timestamp: int, lamport_clock: int, author_pubkey: str,
                      is_deleted: int = 0, comment: str,
                      signature: str) -> bool:
    ex = db.execute(
        "SELECT lamport_clock,timestamp FROM comments_user"
        " WHERE id=?", (id,)).fetchone()
    if ex and not _wins(lamport_clock, timestamp,
                        ex["lamport_clock"], ex["timestamp"]):
        return False
    if ex:
        db.execute(
            "UPDATE comments_user SET timestamp=?,lamport_clock=?,"
            "author_pubkey=?,is_deleted=?,comment=?,signature=? WHERE id=?",
            (timestamp, lamport_clock, author_pubkey, is_deleted,
             comment, signature, id))
    else:
        db.execute(
            "INSERT INTO comments_user(id,belongs_to,timestamp,lamport_clock,"
            "author_pubkey,is_deleted,comment,signature) VALUES(?,?,?,?,?,?,?,?)",
            (id, belongs_to, timestamp, lamport_clock, author_pubkey,
             is_deleted, comment, signature))
    db.commit()
    return True


def save_comment_system(db: sqlite3.Connection, *, id: str, belongs_to: str,
                        timestamp: int, comment: str) -> None:
    """Local-only. No signature, no sync."""
    db.execute(
        "INSERT OR IGNORE INTO comments_system"
        "(id,belongs_to,timestamp,comment) VALUES(?,?,?,?)",
        (id, belongs_to, timestamp, comment))
    db.commit()


def get_comments(db: sqlite3.Connection,
                 belongs_to: str) -> list[sqlite3.Row]:
    """User + system comments merged and sorted by timestamp."""
    user = db.execute(
        "SELECT id,belongs_to,timestamp,author_pubkey,comment,'user' as kind"
        " FROM comments_user WHERE belongs_to=? AND is_deleted=0",
        (belongs_to,)).fetchall()
    sys_ = db.execute(
        "SELECT id,belongs_to,timestamp,'' as author_pubkey,comment,'system' as kind"
        " FROM comments_system WHERE belongs_to=? AND is_deleted=0",
        (belongs_to,)).fetchall()
    result = list(user) + list(sys_)
    result.sort(key=lambda r: r["timestamp"])
    return result


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------

def save_attachment(db: sqlite3.Connection, *, id: str, belongs_to: str,
                    timestamp: int, lamport_clock: int, author_pubkey: str,
                    sha256: str, filename: str, mime: str = None,
                    size: int = None, signature: str) -> bool:
    ex = db.execute(
        "SELECT lamport_clock,timestamp FROM attachments"
        " WHERE id=?", (id,)).fetchone()
    if ex and not _wins(lamport_clock, timestamp,
                        ex["lamport_clock"], ex["timestamp"]):
        return False
    if ex:
        db.execute(
            "UPDATE attachments SET timestamp=?,lamport_clock=?,"
            "author_pubkey=?,sha256=?,filename=?,mime=?,size=?,"
            "signature=? WHERE id=?",
            (timestamp, lamport_clock, author_pubkey, sha256, filename,
             mime, size, signature, id))
    else:
        db.execute(
            "INSERT INTO attachments(id,belongs_to,timestamp,lamport_clock,"
            "author_pubkey,sha256,filename,mime,size,is_stored,signature)"
            " VALUES(?,?,?,?,?,?,?,?,?,0,?)",
            (id, belongs_to, timestamp, lamport_clock, author_pubkey,
             sha256, filename, mime, size, signature))
    db.commit()
    return True


def mark_attachment_stored(db: sqlite3.Connection, sha256: str) -> None:
    """Mark file as present on disk. Local state only — never synced."""
    db.execute(
        "UPDATE attachments SET is_stored=1 WHERE sha256=?", (sha256,))
    db.commit()


def mark_attachment_deleted(db: sqlite3.Connection, sha256: str) -> None:
    """Mark file as present on disk. Local state only — never synced."""
    db.execute(
        "UPDATE attachments SET is_stored=2 WHERE sha256=?", (sha256,))
    db.commit()


def get_attachments(db: sqlite3.Connection,
                    expense_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM attachments WHERE belongs_to=?",
        (expense_id,)).fetchall()


def attachment_exists(sha256: str) -> bool:
    if not STORAGE_DIR:
        return False
    return os.path.exists(os.path.join(STORAGE_DIR, sha256))


def attachment_path(sha256: str) -> Optional[str]:
    path = os.path.join(STORAGE_DIR, sha256)
    return path if os.path.exists(path) else None


# ---------------------------------------------------------------------------
# exchange_rates
# ---------------------------------------------------------------------------

def save_rate(db: sqlite3.Connection, base: str, target: str,
              rate: float) -> None:
    db.execute(
        "INSERT OR REPLACE INTO exchange_rates(base,target,rate,fetched_at)"
        " VALUES(?,?,?,?)", (base, target, rate, int(time.time())))
    db.commit()


def get_rate(db: sqlite3.Connection, base: str,
             target: str) -> Optional[float]:
    row = db.execute(
        "SELECT rate FROM exchange_rates WHERE base=? AND target=?",
        (base, target)).fetchone()
    return row["rate"] if row else None


# ---------------------------------------------------------------------------
# Delta sync — used by network.py history protocol
# ---------------------------------------------------------------------------

def get_lamport_map(db: sqlite3.Connection,
                    group_id: str = None) -> dict:
    """
    Returns {expenses:{id:lamport}, settlements:{id:lamport},
             comments:{id:lamport}, splits:{id:lamport},
             users:{pubkey:lamport}, attachments:{id:lamport}}
    Sent to peers so they can compute what we are missing.
    """
    def _m(rows) -> dict:
        return {r[0]: r[1] for r in rows}

    w    = " WHERE group_id=?" if group_id else ""
    args = (group_id,) if group_id else ()
    return {
        "expenses":    _m(db.execute(
            f"SELECT id,lamport_clock FROM expenses{w}", args).fetchall()),
        "settlements": _m(db.execute(
            f"SELECT id,lamport_clock FROM settlements{w}", args).fetchall()),
        # Users: composite key encoded as "public_key:group_id"
        "users":       {f"{r[0]}:{r[1]}": r[2] for r in db.execute(
            "SELECT public_key,group_id,lamport_clock FROM users"
            + (" WHERE group_id=?" if group_id else ""),
            (group_id,) if group_id else ()).fetchall()},
        "comments":    _m(db.execute(
            "SELECT id,lamport_clock FROM comments_user").fetchall()),
        "splits":      _m(db.execute(
            "SELECT id,lamport_clock FROM split").fetchall()),
        "attachments": _m(db.execute(
            "SELECT id,lamport_clock FROM attachments").fetchall()),
    }


def get_records_unknown_to(db: sqlite3.Connection,
                            known: dict,
                            group_id: str) -> dict:
    """Records the remote peer doesn't have or has older versions of."""
    def _new(rows, table_known: dict, key: str = "id") -> list:
        return [r for r in rows
                if r[key] not in table_known
                or table_known[r[key]] < r["lamport_clock"]]

    w    = " WHERE group_id=?" if group_id else ""
    args = (group_id,) if group_id else ()
    return {
        "expenses":    _new(db.execute(
            f"SELECT * FROM expenses{w}", args).fetchall(),
            known.get("expenses", {})),
        "settlements": _new(db.execute(
            f"SELECT * FROM settlements{w}", args).fetchall(),
            known.get("settlements", {})),
        # Users: match against composite "public_key:group_id" key
        "users":       [r for r in db.execute(
            "SELECT * FROM users"
            + (" WHERE group_id=?" if group_id else ""),
            (group_id,) if group_id else ()).fetchall()
                        if f"{r['public_key']}:{r['group_id']}"
                        not in known.get("users", {})
                        or known["users"]
                        [f"{r['public_key']}:{r['group_id']}"] < r["lamport_clock"]],
        "comments":    _new(db.execute(
            "SELECT * FROM comments_user").fetchall(),
            known.get("comments", {})),
        "splits":      _new(db.execute(
            "SELECT * FROM split").fetchall(),
            known.get("splits", {})),
        "attachments": _new(db.execute(
            "SELECT * FROM attachments").fetchall(),
            known.get("attachments", {})),
    }


# ---------------------------------------------------------------------------
# CRDT merge
# ---------------------------------------------------------------------------

def _wins(new_lc: int, new_ts: int,
          old_lc: int, old_ts: int,
          new_author: str = "", old_author: str = "") -> bool:
    """
    Three-level priority:
      1. Lamport clock (higher = newer)
      2. Wall-clock timestamp (tiebreak)
      3. Author pubkey lexicographic order (deterministic tiebreak)
    """
    if new_lc != old_lc:   return new_lc > old_lc
    if new_ts != old_ts:   return new_ts > old_ts
    return new_author > old_author
