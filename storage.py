# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Storage Module – SQLite-Persistenz.

Ausgaben und Ausgleichszahlungen werden als verschlüsselte Blobs gespeichert.
Dateianhänge als Binärdaten unter storage/<sha256>.
CRDT: Lamport-Uhr + deterministisches Tiebreaking.
Merge-Prioritaet: lamport_clock > timestamp > author_pubkey (lexikografisch).
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
    Merge-Entscheidung: gewinnt die neue Version ueber die gespeicherte?

    Prioritaet:
      1. Lamport-Uhr    - uhrzeit-unabhaengig, kausal korrekt
      2. Wanduhr        - Tiebreaker bei identischer Lamport-Uhr
                         (kann bei gleichzeitiger Erstellung gleich sein)
      3. author_pubkey  - deterministischer letzter Tiebreaker;
                         lexikografisch groesserer Schluessel gewinnt.
                         Beide Seiten kommen zum selben Ergebnis ohne
                         Kommunikation -> keine Split-Brain-Moeglichkeit.
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
        logger.debug("CRDT: verworfen (Lamport %d <= %d, ts %d <= %d)",
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


def delete_attachment_if_unreferenced(
        db: sqlite3.Connection, sha256: str) -> bool:
    """
    Loescht die Anhang-Datei aus dem Dateisystem, falls kein
    nicht-geloeschter Expense-Eintrag mehr auf diesen SHA-256 verweist.

    Warum 'unreferenced' pruefen?
      Zwei Ausgaben koennen dieselbe Datei referenzieren (selber Kassenbon
      zweimal hinzugefuegt). In diesem Fall bleibt die Datei erhalten.
      Der DB-Tombstone (is_deleted=1) bleibt immer erhalten damit
      andere Peers die Loeschung per Sync erhalten koennen.

    Gibt True zurueck wenn die Datei geloescht wurde, False sonst.
    """
    path = os.path.join(STORAGE_DIR, sha256)
    if not os.path.exists(path):
        return False  # existiert nicht mehr

    # Alle Blobs laden und pruefen ob noch jemand diesen Hash referenziert
    # Wir checken auf Blob-Ebene (ohne Entschluesselung) ob der hex-String
    # im Blob vorkommt -- als schnellen Heuristik-Filter.
    # Exakt: nur nicht-geloeschte Eintraege zaehlen.
    rows = db.execute(
        "SELECT blob FROM expenses WHERE is_deleted = 0"
    ).fetchall()
    sha_bytes = sha256.encode()
    for row in rows:
        if sha_bytes in bytes(row["blob"]):
            logger.debug("Attachment %s noch referenziert, nicht geloescht",
                         sha256[:12])
            return False

    try:
        os.remove(path)
        logger.info("Attachment geloescht: %s", sha256[:12])
        return True
    except OSError as e:
        logger.warning("Attachment loeschen fehlgeschlagen %s: %s",
                       sha256[:12], e)
        return False


# ---------------------------------------------------------------------------
# History-Sync Hilfsfunktionen (für network.py)
# ---------------------------------------------------------------------------

def load_all_expense_blobs_since(since_ts: int) -> list[tuple[str, bytes]]:
    """Alle Expense-Blobs mit timestamp > since_ts (inkl. gelöschter für Tombstone-Sync)."""
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
    """Alle Settlement-Blobs mit timestamp > since_ts."""
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
    """Höchster bekannter Timestamp über Expenses und Settlements."""
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
