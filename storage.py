# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Storage Module – SQLite-Persistenz.

Ausgaben und Ausgleichszahlungen werden als verschlüsselte Blobs gespeichert.
Dateianhänge als Binärdaten unter storage/<sha256>.
CRDT: last-write-wins per Timestamp.
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
    id          TEXT PRIMARY KEY,
    blob        BLOB NOT NULL,
    timestamp   INTEGER NOT NULL,
    is_deleted  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settlements (
    id          TEXT PRIMARY KEY,
    blob        BLOB NOT NULL,
    timestamp   INTEGER NOT NULL,
    is_deleted  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS members (
    pubkey      TEXT PRIMARY KEY,
    data_json   TEXT NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_expenses_ts   ON expenses(timestamp);
CREATE INDEX IF NOT EXISTS idx_settlements_ts ON settlements(timestamp);
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

def _save_blob(db: sqlite3.Connection, table: str, obj_id: str,
               blob: bytes, timestamp: int, is_deleted: bool = False) -> bool:
    row = db.execute(
        f"SELECT timestamp FROM {table} WHERE id = ?", (obj_id,)
    ).fetchone()
    if row and timestamp <= row["timestamp"]:
        return False
    db.execute(
        f"INSERT OR REPLACE INTO {table} (id, blob, timestamp, is_deleted) VALUES (?,?,?,?)",
        (obj_id, blob, timestamp, int(is_deleted)),
    )
    db.commit()
    return True


def _load_blobs(db: sqlite3.Connection, table: str) -> list[tuple[str, bytes]]:
    rows = db.execute(
        f"SELECT id, blob FROM {table} WHERE is_deleted = 0 ORDER BY timestamp ASC"
    ).fetchall()
    return [(r["id"], bytes(r["blob"])) for r in rows]


def _soft_delete_blob(db: sqlite3.Connection, table: str, obj_id: str,
                      new_blob: bytes, new_timestamp: int) -> None:
    db.execute(
        f"INSERT OR REPLACE INTO {table} (id, blob, timestamp, is_deleted) VALUES (?,?,?,1)",
        (obj_id, new_blob, new_timestamp),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Ausgaben
# ---------------------------------------------------------------------------

def save_expense_blob(db, eid, blob, ts, is_deleted=False):
    return _save_blob(db, "expenses", eid, blob, ts, is_deleted)

def load_all_expense_blobs(db):
    return _load_blobs(db, "expenses")

def soft_delete_expense_blob(db, eid, blob, ts):
    _soft_delete_blob(db, "expenses", eid, blob, ts)


# ---------------------------------------------------------------------------
# Ausgleichszahlungen
# ---------------------------------------------------------------------------

def save_settlement_blob(db, sid, blob, ts, is_deleted=False):
    return _save_blob(db, "settlements", sid, blob, ts, is_deleted)

def load_all_settlement_blobs(db):
    return _load_blobs(db, "settlements")

def soft_delete_settlement_blob(db, sid, blob, ts):
    _soft_delete_blob(db, "settlements", sid, blob, ts)


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
# Dateianhänge
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
