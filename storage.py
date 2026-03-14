# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Storage Module

SQLite speichert Ausgaben als verschlüsselte Blobs — ohne das
Gruppenpasswort ist der Datenbankinhalt wertlos.

Dateianhänge liegen als Binärdaten unter storage/<sha256> auf der Platte.
Der SHA-256-Hash ist Teil der Expense-Signatur, Manipulationen werden erkannt.

CRDT: last-write-wins per Timestamp (für spätere P2P-Synchronisation).
"""

import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

STORAGE_DIR = "storage"

_DDL = """
CREATE TABLE IF NOT EXISTS expenses (
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

CREATE INDEX IF NOT EXISTS idx_expenses_ts ON expenses(timestamp);
"""


def init_db(db_path: str = "splitp2p.db") -> sqlite3.Connection:
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
# Ausgaben (verschlüsselt)
# ---------------------------------------------------------------------------

def save_expense_blob(
    db: sqlite3.Connection,
    expense_id: str,
    blob: bytes,
    timestamp: int,
    is_deleted: bool = False,
) -> bool:
    """
    CRDT-merge: speichert nur wenn neu oder Timestamp neuer.
    blob = Ergebnis von crypto.encrypt_expense().
    """
    row = db.execute(
        "SELECT timestamp FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()

    if row and timestamp <= row["timestamp"]:
        logger.debug("Stale update für %s ignoriert", expense_id[:8])
        return False

    db.execute(
        "INSERT OR REPLACE INTO expenses (id, blob, timestamp, is_deleted) VALUES (?,?,?,?)",
        (expense_id, blob, timestamp, int(is_deleted)),
    )
    db.commit()
    return True


def load_all_expense_blobs(db: sqlite3.Connection) -> list[tuple[str, bytes]]:
    """Gibt (id, blob) für alle nicht gelöschten Ausgaben zurück."""
    rows = db.execute(
        "SELECT id, blob FROM expenses WHERE is_deleted = 0 ORDER BY timestamp ASC"
    ).fetchall()
    return [(r["id"], bytes(r["blob"])) for r in rows]


def soft_delete_expense_blob(
    db: sqlite3.Connection,
    expense_id: str,
    new_blob: bytes,
    new_timestamp: int,
) -> None:
    """
    Tombstone: aktualisiert Blob + Timestamp, setzt is_deleted=1.
    Der neue Blob enthält die Ausgabe mit is_deleted=True (für Sync).
    """
    db.execute(
        "INSERT OR REPLACE INTO expenses (id, blob, timestamp, is_deleted) VALUES (?,?,?,1)",
        (expense_id, new_blob, new_timestamp),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Mitglieder (Klartext – nur öffentliche Infos)
# ---------------------------------------------------------------------------

def save_member(db: sqlite3.Connection, member) -> None:
    import json
    db.execute(
        "INSERT OR REPLACE INTO members (pubkey, data_json, updated_at) VALUES (?,?,?)",
        (member.pubkey, json.dumps(member.to_dict()), member.joined_at),
    )
    db.commit()


def load_all_members(db: sqlite3.Connection):
    import json
    from models import Member
    rows = db.execute("SELECT data_json FROM members").fetchall()
    result = []
    for row in rows:
        try:
            result.append(Member.from_dict(json.loads(row["data_json"])))
        except Exception as e:
            logger.warning("Member-Deserialisierung fehlgeschlagen: %s", e)
    return result


def get_member(db: sqlite3.Connection, pubkey: str) -> Optional[object]:
    import json
    from models import Member
    row = db.execute(
        "SELECT data_json FROM members WHERE pubkey = ?", (pubkey,)
    ).fetchone()
    return Member.from_dict(json.loads(row["data_json"])) if row else None


# ---------------------------------------------------------------------------
# Dateianhänge
# ---------------------------------------------------------------------------

def save_attachment(data: bytes, sha256: str) -> str:
    """
    Speichert Rohdaten einer Datei unter storage/<sha256>.
    Gibt den vollständigen Pfad zurück.
    Idempotent: existiert die Datei schon, wird sie nicht überschrieben.
    """
    os.makedirs(STORAGE_DIR, exist_ok=True)
    path = os.path.join(STORAGE_DIR, sha256)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
        logger.info("Anhang gespeichert: %s (%d Bytes)", sha256[:12], len(data))
    return path


def attachment_path(sha256: str) -> Optional[str]:
    """Pfad zur gespeicherten Datei, oder None wenn nicht vorhanden."""
    path = os.path.join(STORAGE_DIR, sha256)
    return path if os.path.exists(path) else None


def attachment_exists(sha256: str) -> bool:
    return os.path.exists(os.path.join(STORAGE_DIR, sha256))
