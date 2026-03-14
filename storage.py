# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Storage Module – SQLite persistence with CRDT merge semantics.

Messages are stored as encrypted blobs so the database itself leaks
no plaintext. CRDT (last-write-wins by timestamp) ensures consistent
state after peer synchronisation.
"""

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    id                    TEXT PRIMARY KEY,
    creator_pubkey        TEXT    NOT NULL,
    timestamp             INTEGER NOT NULL,
    content_json_encrypted TEXT   NOT NULL,
    nonce                 TEXT    NOT NULL,
    signature             TEXT    NOT NULL,
    local_update_id       INTEGER NOT NULL DEFAULT 0,
    is_deleted            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS _sequence (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db(db_path: str = "p2p_storage.db") -> sqlite3.Connection:
    """
    Open (or create) the SQLite database and apply the schema.

    Args:
        db_path: Path to the SQLite file. Use ":memory:" for tests.

    Returns:
        Open sqlite3 connection.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    for statement in _DDL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)

    conn.execute(
        "INSERT OR IGNORE INTO _sequence (name, value) VALUES ('local_update_id', 0)"
    )
    conn.commit()
    logger.info("Database initialised at '%s'", db_path)
    return conn


# ---------------------------------------------------------------------------
# CRDT merge
# ---------------------------------------------------------------------------

def merge_message(db: sqlite3.Connection, msg: dict) -> bool:
    """
    CRDT last-write-wins merge.

    Inserts the message if it is new, or replaces it if the incoming
    timestamp is strictly newer than the stored one.

    Args:
        db:  Open database connection.
        msg: Packet dict; must contain the fields listed in the schema.

    Returns:
        True if the database was updated, False if the message was ignored.
    """
    row = db.execute(
        "SELECT timestamp FROM messages WHERE id = ?", (msg["id"],)
    ).fetchone()

    if row and msg.get("timestamp", 0) <= row["timestamp"]:
        logger.debug("Ignored stale update for message %s", msg["id"])
        return False

    # Advance the local sequence counter
    db.execute(
        "UPDATE _sequence SET value = value + 1 WHERE name = 'local_update_id'"
    )
    seq = db.execute(
        "SELECT value FROM _sequence WHERE name = 'local_update_id'"
    ).fetchone()[0]

    db.execute(
        """
        INSERT OR REPLACE INTO messages
            (id, creator_pubkey, timestamp, content_json_encrypted,
             nonce, signature, local_update_id, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            msg["id"],
            msg.get("creator_pubkey", ""),
            msg.get("timestamp", 0),
            msg.get("encrypted_payload", ""),
            msg.get("nonce", ""),
            msg.get("signature", ""),
            seq,
            int(msg.get("is_deleted", False)),
        ),
    )
    db.commit()
    logger.info("Stored message %s (local_update_id=%d)", msg["id"], seq)
    return True


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_all_messages(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all non-deleted messages ordered by timestamp."""
    rows = db.execute(
        "SELECT * FROM messages WHERE is_deleted = 0 ORDER BY timestamp ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_messages_since(
    db: sqlite3.Connection, local_update_id: int
) -> list[dict[str, Any]]:
    """
    Return messages inserted/updated after *local_update_id*.

    Useful for incremental sync: a peer sends its highest known
    local_update_id and receives only the delta.
    """
    rows = db.execute(
        "SELECT * FROM messages WHERE local_update_id > ? ORDER BY timestamp ASC",
        (local_update_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def soft_delete_message(db: sqlite3.Connection, msg_id: str) -> bool:
    """Mark a message as deleted (tombstone) instead of removing it."""
    db.execute(
        "UPDATE messages SET is_deleted = 1 WHERE id = ?", (msg_id,)
    )
    db.commit()
    return db.execute(
        "SELECT changes()"
    ).fetchone()[0] > 0
