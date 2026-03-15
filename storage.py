# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Storage Module – SQLite-Persistenz.

Expenses and settlements stored as encrypted blobs.
File attachments as binary data under storage/<sha256>.
CRDT: Lamport clock + deterministic tiebreaking.
Merge priority: lamport_clock > timestamp > author_pubkey (lexicographic).
"""

import json
import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

STORAGE_DIR = "storage"
DB_PATH     = "splitp2p.db"


def configure_paths(db_path: str, storage_dir: str) -> None:
    global DB_PATH, STORAGE_DIR
    DB_PATH     = db_path
    STORAGE_DIR = storage_dir
    logger.info("Paths set: db=%s  storage=%s", db_path, storage_dir)


from currency import RATES_DDL as _RATES_DDL

_DDL = """
CREATE TABLE IF NOT EXISTS expenses (
    id            TEXT PRIMARY KEY,
    blob          BLOB NOT NULL,
    timestamp     INTEGER NOT NULL,
    lamport_clock INTEGER NOT NULL DEFAULT 0,
    author_pubkey TEXT    NOT NULL DEFAULT '',
    is_deleted    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settlements (
    id            TEXT PRIMARY KEY,
    blob          BLOB NOT NULL,
    timestamp     INTEGER NOT NULL,
    lamport_clock INTEGER NOT NULL DEFAULT 0,
    author_pubkey TEXT    NOT NULL DEFAULT '',
    is_deleted    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS members (
    pubkey      TEXT PRIMARY KEY,
    data_json   TEXT NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_expenses_ts    ON expenses(timestamp);
CREATE INDEX IF NOT EXISTS idx_expenses_lc    ON expenses(lamport_clock);
CREATE INDEX IF NOT EXISTS idx_settlements_ts ON settlements(timestamp);
CREATE INDEX IF NOT EXISTS idx_settlements_lc ON settlements(lamport_clock);
""" + "\n" + _RATES_DDL


def init_db(db_path: str = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    os.makedirs(STORAGE_DIR, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for stmt in _DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()
    logger.info("DB ready: %s", db_path)
    return conn


# ---------------------------------------------------------------------------
# Generisches CRDT-Blob-Store (Expenses + Settlements teilen die Logik)
# ---------------------------------------------------------------------------

def _wins_over(new_lc: int, new_ts: int, new_pk: str,
               old_lc: int, old_ts: int, old_pk: str) -> bool:
    """
    Merge decision: does the new version win over the stored one?

    Priority:
      1. Lamport clock  - clock-drift-independent, causally correct
      2. Wall clock     - tiebreaker when Lamport clocks are equal
                         (possible with simultaneous creation)
      3. author_pubkey  - deterministic final tiebreaker;
                         lexicographically larger key wins.
                         Both sides reach the same result without
                         communication -> no split-brain possible.
    """
    if new_lc != old_lc:
        return new_lc > old_lc
    if new_ts != old_ts:
        return new_ts > old_ts
    return new_pk > old_pk  # lexikografisch


def _save_blob(db: sqlite3.Connection, table: str, obj_id: str,
               blob: bytes, timestamp: int, is_deleted: bool = False,
               lamport_clock: int = 0, author_pubkey: str = "") -> bool:
    row = db.execute(
        f"SELECT timestamp, lamport_clock, author_pubkey FROM {table} WHERE id = ?",
        (obj_id,)
    ).fetchone()
    if row and not _wins_over(
        lamport_clock, timestamp, author_pubkey,
        row["lamport_clock"], row["timestamp"], row["author_pubkey"],
    ):
        logger.debug("CRDT: rejected (Lamport %d <= %d, ts %d <= %d)",
                     lamport_clock, row["lamport_clock"],
                     timestamp, row["timestamp"])
        return False
    db.execute(
        f"INSERT OR REPLACE INTO {table}"
        f" (id, blob, timestamp, lamport_clock, author_pubkey, is_deleted)"
        f" VALUES (?,?,?,?,?,?)",
        (obj_id, blob, timestamp, lamport_clock, author_pubkey, int(is_deleted)),
    )
    db.commit()
    return True


def _load_blobs(db: sqlite3.Connection, table: str) -> list[tuple[str, bytes]]:
    rows = db.execute(
        f"SELECT id, blob FROM {table} WHERE is_deleted = 0 ORDER BY timestamp ASC"
    ).fetchall()
    return [(r["id"], bytes(r["blob"])) for r in rows]


def _soft_delete_blob(db: sqlite3.Connection, table: str, obj_id: str,
                      new_blob: bytes, new_timestamp: int,
                      lamport_clock: int = 0, author_pubkey: str = "") -> None:
    db.execute(
        f"INSERT OR REPLACE INTO {table}"
        f" (id, blob, timestamp, lamport_clock, author_pubkey, is_deleted)"
        f" VALUES (?,?,?,?,?,1)",
        (obj_id, new_blob, new_timestamp, lamport_clock, author_pubkey),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Ausgaben
# ---------------------------------------------------------------------------

def save_expense_blob(db, eid, blob, ts, is_deleted=False,
                      lamport_clock=0, author_pubkey=""):
    return _save_blob(db, "expenses", eid, blob, ts, is_deleted,
                     lamport_clock, author_pubkey)

def load_all_expense_blobs(db):
    return _load_blobs(db, "expenses")

def soft_delete_expense_blob(db, eid, blob, ts,
                             lamport_clock=0, author_pubkey=""):
    _soft_delete_blob(db, "expenses", eid, blob, ts, lamport_clock, author_pubkey)


# ---------------------------------------------------------------------------
# Ausgleichszahlungen
# ---------------------------------------------------------------------------

def save_settlement_blob(db, sid, blob, ts, is_deleted=False,
                         lamport_clock=0, author_pubkey=""):
    return _save_blob(db, "settlements", sid, blob, ts, is_deleted,
                     lamport_clock, author_pubkey)

def load_all_settlement_blobs(db):
    return _load_blobs(db, "settlements")

def soft_delete_settlement_blob(db, sid, blob, ts,
                                lamport_clock=0, author_pubkey=""):
    _soft_delete_blob(db, "settlements", sid, blob, ts, lamport_clock, author_pubkey)


# ---------------------------------------------------------------------------
# Mitglieder
# ---------------------------------------------------------------------------

def save_member(db: sqlite3.Connection, member) -> None:
    db.execute(
        "INSERT OR REPLACE INTO members (pubkey, data_json, updated_at) VALUES (?,?,?)",
        (member.pubkey, json.dumps(member.to_dict()), member.joined_at),
    )
    db.commit()


def load_all_members(db: sqlite3.Connection):
    from models import Member
    rows = db.execute("SELECT data_json FROM members").fetchall()
    result = []
    for row in rows:
        try:
            result.append(Member.from_dict(json.loads(row["data_json"])))
        except Exception as e:
            logger.warning("Member parse error: %s", e)
    return result


def get_member(db: sqlite3.Connection, pubkey: str):
    from models import Member
    row = db.execute(
        "SELECT data_json FROM members WHERE pubkey = ?", (pubkey,)
    ).fetchone()
    return Member.from_dict(json.loads(row["data_json"])) if row else None


# ---------------------------------------------------------------------------
# File attachments
# ---------------------------------------------------------------------------

def save_attachment(data: bytes, sha256: str) -> str:
    os.makedirs(STORAGE_DIR, exist_ok=True)
    path = os.path.join(STORAGE_DIR, sha256)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
        logger.info("Attachment saved: %s (%d B)", sha256[:12], len(data))
    return path


def attachment_path(sha256: str) -> Optional[str]:
    path = os.path.join(STORAGE_DIR, sha256)
    return path if os.path.exists(path) else None


def attachment_exists(sha256: str) -> bool:
    return os.path.exists(os.path.join(STORAGE_DIR, sha256))


def delete_attachment_if_unreferenced(
        db: sqlite3.Connection, sha256: str) -> bool:
    """
    Deletes the attachment file from disk if no active (non-deleted)
    expense entry references this SHA-256 anymore.

    Why check 'unreferenced'?
      Two expenses can reference the same file (same receipt added twice).
      In that case the file is kept.
      The DB tombstone (is_deleted=1) always stays so other peers
      receive the deletion via sync.

    Returns True if the file was deleted, False otherwise.
    """
    path = os.path.join(STORAGE_DIR, sha256)
    if not os.path.exists(path):
        return False  # file already gone

    # Load all blobs and check if any active entry still references this hash.
    # We check at blob level (without decryption) whether the hex string
    # appears in the blob - fast heuristic filter.
    # Only non-deleted entries count.
    rows = db.execute(
        "SELECT blob FROM expenses WHERE is_deleted = 0"
    ).fetchall()
    sha_bytes = sha256.encode()
    for row in rows:
        if sha_bytes in bytes(row["blob"]):
            logger.debug("Attachment %s still referenced, not deleted",
                         sha256[:12])
            return False

    try:
        os.remove(path)
        logger.info("Attachment deleted: %s", sha256[:12])
        return True
    except OSError as e:
        logger.warning("Failed to delete attachment %s: %s",
                       sha256[:12], e)
        return False


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

_COMMENTS_DDL = """
CREATE TABLE IF NOT EXISTS comments (
    id            TEXT PRIMARY KEY,
    expense_id    TEXT NOT NULL,
    blob          BLOB NOT NULL,
    timestamp     INTEGER NOT NULL,
    lamport_clock INTEGER NOT NULL DEFAULT 0,
    author_pubkey TEXT    NOT NULL DEFAULT '',
    is_deleted    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_comments_exp ON comments(expense_id);
CREATE INDEX IF NOT EXISTS idx_comments_lc  ON comments(lamport_clock);
"""


def _ensure_comments_table(db: sqlite3.Connection) -> None:
    """Idempotent: creates comments table if not present (migration helper)."""
    for stmt in _COMMENTS_DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            db.execute(s)
    db.commit()


def save_comment_blob(db: sqlite3.Connection, comment_id: str,
                      expense_id: str, blob: bytes,
                      timestamp: int, is_deleted: bool = False,
                      lamport_clock: int = 0,
                      author_pubkey: str = "") -> bool:
    """CRDT-safe save: same merge rules as expenses."""
    _ensure_comments_table(db)
    row = db.execute(
        "SELECT timestamp, lamport_clock, author_pubkey FROM comments WHERE id = ?",
        (comment_id,)
    ).fetchone()
    if row and not _wins_over(
        lamport_clock, timestamp, author_pubkey,
        row["lamport_clock"], row["timestamp"], row["author_pubkey"],
    ):
        return False
    db.execute(
        "INSERT OR REPLACE INTO comments"
        " (id, expense_id, blob, timestamp, lamport_clock, author_pubkey, is_deleted)"
        " VALUES (?,?,?,?,?,?,?)",
        (comment_id, expense_id, blob, timestamp,
         lamport_clock, author_pubkey, int(is_deleted)),
    )
    db.commit()
    return True


def load_comments_for_expense(db: sqlite3.Connection,
                               expense_id: str) -> list[tuple[str, bytes]]:
    """Returns (id, blob) pairs for all non-deleted comments on an expense."""
    _ensure_comments_table(db)
    rows = db.execute(
        "SELECT id, blob FROM comments"
        " WHERE expense_id = ? AND is_deleted = 0"
        " ORDER BY lamport_clock ASC, timestamp ASC",
        (expense_id,)
    ).fetchall()
    return [(r["id"], bytes(r["blob"])) for r in rows]


def load_all_comment_blobs_since(since_ts: int) -> list[tuple[str, str, bytes]]:
    """Returns (id, expense_id, blob) for delta history sync."""
    import sqlite3 as _sq
    try:
        conn = _sq.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = _sq.Row
        rows = conn.execute(
            "SELECT id, expense_id, blob FROM comments"
            " WHERE timestamp > ? ORDER BY timestamp ASC",
            (since_ts,),
        ).fetchall()
        conn.close()
        return [(r["id"], r["expense_id"], bytes(r["blob"])) for r in rows]
    except Exception:
        return []


def soft_delete_comment_blob(db: sqlite3.Connection, comment_id: str,
                              blob: bytes, timestamp: int,
                              lamport_clock: int = 0,
                              author_pubkey: str = "") -> None:
    """Tombstone a comment (keeps id for sync propagation)."""
    _ensure_comments_table(db)
    db.execute(
        "INSERT OR REPLACE INTO comments"
        " (id, expense_id, blob, timestamp, lamport_clock, author_pubkey, is_deleted)"
        " VALUES ((SELECT expense_id FROM comments WHERE id=?),?,?,?,?,?,1)",
        (comment_id, blob, timestamp, lamport_clock, author_pubkey, comment_id),
    )
    db.commit()


def get_comment_count(db: sqlite3.Connection, expense_id: str) -> int:
    """Fast count of non-deleted comments for an expense (for the badge)."""
    _ensure_comments_table(db)
    row = db.execute(
        "SELECT COUNT(*) as n FROM comments"
        " WHERE expense_id = ? AND is_deleted = 0",
        (expense_id,)
    ).fetchone()
    return int(row["n"] if row else 0)


# ---------------------------------------------------------------------------
# History sync helpers (used by network.py)
# ---------------------------------------------------------------------------

def load_all_expense_blobs_since(since_ts: int) -> list[tuple[str, bytes]]:
    """All expense blobs with timestamp > since_ts (incl. deleted for tombstone sync)."""
    import sqlite3 as _sq
    conn = _sq.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = _sq.Row
    rows = conn.execute(
        "SELECT id, blob FROM expenses WHERE timestamp > ? ORDER BY timestamp ASC",
        (since_ts,),
    ).fetchall()
    conn.close()
    return [(r["id"], bytes(r["blob"])) for r in rows]


def load_all_settlement_blobs_since(since_ts: int) -> list[tuple[str, bytes]]:
    """All settlement blobs with timestamp > since_ts."""
    import sqlite3 as _sq
    conn = _sq.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = _sq.Row
    rows = conn.execute(
        "SELECT id, blob FROM settlements WHERE timestamp > ? ORDER BY timestamp ASC",
        (since_ts,),
    ).fetchall()
    conn.close()
    return [(r["id"], bytes(r["blob"])) for r in rows]


def get_max_timestamp() -> int:
    """Highest known timestamp across expenses and settlements."""
    import sqlite3 as _sq
    conn = _sq.connect(DB_PATH, check_same_thread=False)
    row = conn.execute(
        "SELECT MAX(ts) as m FROM ("
        "  SELECT MAX(timestamp) as ts FROM expenses"
        "  UNION ALL"
        "  SELECT MAX(timestamp) as ts FROM settlements"
        ")"
    ).fetchone()
    conn.close()
    return int(row[0] or 0)


def get_max_lamport_clock() -> int:
    """
    Highest known Lamport clock value across expenses and settlements.
    Used to restore the local Lamport clock after a restart so that
    new entries always have a higher clock than any stored entry.
    """
    import sqlite3 as _sq
    conn = _sq.connect(DB_PATH, check_same_thread=False)
    row = conn.execute(
        "SELECT MAX(lc) as m FROM ("
        "  SELECT MAX(lamport_clock) as lc FROM expenses"
        "  UNION ALL"
        "  SELECT MAX(lamport_clock) as lc FROM settlements"
        ")"
    ).fetchone()
    conn.close()
    return int(row[0] or 0)
