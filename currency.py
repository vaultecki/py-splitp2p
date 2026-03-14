# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Currency Module

Wechselkurse werden von einer kostenlosen API geholt und lokal
in SQLite gecacht. Bei Offline-Betrieb werden die zuletzt bekannten
Kurse verwendet.

Erneuerungsstrategie: "unregelmäßige Abstände"
  - Basis-Intervall: 6 Stunden
  - Jitter: ±0–3 Stunden (zufällig)
  → Verhindert, dass alle Nodes gleichzeitig die API anfragen

API: open.er-api.com – kostenlos, kein API-Key nötig.
Fallback: exchangerate.host (falls erste API nicht erreichbar)
"""

import json
import logging
import random
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# Alle gängigen Währungen die unterstützt werden
SUPPORTED_CURRENCIES = [
    "EUR", "USD", "GBP", "CHF", "JPY", "CNY", "CAD", "AUD",
    "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN",
    "TRY", "BRL", "MXN", "INR", "KRW", "SGD", "HKD", "NZD",
]

# Erneuerungs-Intervall
_BASE_INTERVAL_SEC  = 6 * 3600   # 6 Stunden Basis
_MAX_JITTER_SEC     = 3 * 3600   # ±3 Stunden Jitter

_API_URLS = [
    "https://open.er-api.com/v6/latest/{base}",
    "https://api.exchangerate-api.com/v4/latest/{base}",
]


# ---------------------------------------------------------------------------
# Schema (wird von storage.init_db() eingebunden)
# ---------------------------------------------------------------------------

RATES_DDL = """
CREATE TABLE IF NOT EXISTS exchange_rates (
    base        TEXT NOT NULL,
    target      TEXT NOT NULL,
    rate        REAL NOT NULL,
    fetched_at  INTEGER NOT NULL,
    next_fetch  INTEGER NOT NULL,
    PRIMARY KEY (base, target)
);
"""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _next_fetch_time() -> int:
    """Nächster Fetch-Zeitpunkt mit zufälligem Jitter."""
    jitter = random.randint(0, _MAX_JITTER_SEC)
    return int(time.time()) + _BASE_INTERVAL_SEC + jitter


def fetch_rates_online(base: str) -> Optional[dict[str, float]]:
    """
    Holt aktuelle Kurse von der API.
    Gibt ein Dict {target: rate} zurück oder None bei Fehler.
    """
    base = base.upper()
    for url_tmpl in _API_URLS:
        url = url_tmpl.format(base=base)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SplitP2P/1.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())

            # open.er-api.com gibt {"rates": {...}}
            # exchangerate-api.com gibt {"rates": {...}} auch
            rates = data.get("rates") or data.get("conversion_rates")
            if rates and isinstance(rates, dict):
                logger.info("Kurse für %s geholt von %s (%d Zielwährungen)",
                            base, url, len(rates))
                return {k.upper(): float(v) for k, v in rates.items()}
        except urllib.error.URLError as e:
            logger.warning("API %s nicht erreichbar: %s", url, e)
        except Exception as e:
            logger.warning("Fehler beim Kurse-Abruf von %s: %s", url, e)

    logger.error("Alle APIs fehlgeschlagen – bleibe offline")
    return None


# ---------------------------------------------------------------------------
# Cache (SQLite)
# ---------------------------------------------------------------------------

def save_rates(db: sqlite3.Connection, base: str, rates: dict[str, float]) -> None:
    """Speichert Kurse in der Datenbank."""
    now       = int(time.time())
    next_time = _next_fetch_time()
    base = base.upper()

    db.executemany(
        """INSERT OR REPLACE INTO exchange_rates
           (base, target, rate, fetched_at, next_fetch)
           VALUES (?, ?, ?, ?, ?)""",
        [(base, target.upper(), rate, now, next_time)
         for target, rate in rates.items()],
    )
    db.commit()
    logger.debug("Kurse für %s gespeichert (nächster Fetch ~%s)",
                 base, time.strftime("%H:%M", time.localtime(next_time)))


def load_rates(db: sqlite3.Connection, base: str) -> dict[str, float]:
    """Lädt gecachte Kurse aus der Datenbank."""
    rows = db.execute(
        "SELECT target, rate FROM exchange_rates WHERE base = ?",
        (base.upper(),),
    ).fetchall()
    return {r["target"]: r["rate"] for r in rows}


def rates_need_refresh(db: sqlite3.Connection, base: str) -> bool:
    """True wenn die gecachten Kurse veraltet sind oder fehlen."""
    row = db.execute(
        "SELECT MIN(next_fetch) as nf FROM exchange_rates WHERE base = ?",
        (base.upper(),),
    ).fetchone()
    if not row or row["nf"] is None:
        return True
    return time.time() >= row["nf"]


def rates_age_str(db: sqlite3.Connection, base: str) -> str:
    """Lesbare Altersangabe der gecachten Kurse, z.B. 'vor 2h 14m'."""
    row = db.execute(
        "SELECT MAX(fetched_at) as fa FROM exchange_rates WHERE base = ?",
        (base.upper(),),
    ).fetchone()
    if not row or row["fa"] is None:
        return "nie aktualisiert"
    age = int(time.time()) - row["fa"]
    if age < 60:
        return "gerade eben"
    if age < 3600:
        return f"vor {age // 60}m"
    h, m = divmod(age // 60, 60)
    return f"vor {h}h {m}m" if m else f"vor {h}h"


# ---------------------------------------------------------------------------
# High-level: Kurse holen (Cache oder Online)
# ---------------------------------------------------------------------------

def get_rates(db: sqlite3.Connection, base: str) -> dict[str, float]:
    """
    Gibt aktuelle Wechselkurse zurück.
    Holt online wenn Cache veraltet/leer, sonst aus Cache.
    Fällt auf Cache zurück wenn online fehlschlägt.
    """
    base = base.upper()
    if rates_need_refresh(db, base):
        logger.info("Kurse für %s veraltet – hole online…", base)
        fresh = fetch_rates_online(base)
        if fresh:
            save_rates(db, base, fresh)
            return fresh
        else:
            logger.warning("Online-Abruf fehlgeschlagen – nutze Cache")

    cached = load_rates(db, base)
    if cached:
        return cached

    logger.error("Keine Kurse für %s vorhanden (weder online noch Cache)", base)
    return {}


def force_refresh(db: sqlite3.Connection, base: str) -> bool:
    """
    Erzwingt einen sofortigen Online-Abruf.
    Gibt True zurück wenn erfolgreich.
    """
    fresh = fetch_rates_online(base)
    if fresh:
        save_rates(db, base, fresh)
        return True
    return False


# ---------------------------------------------------------------------------
# Konvertierung
# ---------------------------------------------------------------------------

def convert(
    amount: float,
    from_currency: str,
    to_currency: str,
    rates: dict[str, float],
) -> Optional[float]:
    """
    Konvertiert einen Betrag zwischen zwei Währungen.

    rates muss in Bezug auf eine Basiswährung vorliegen
    (d.h. rates["EUR"] = Kurs EUR/Basis).

    Gibt None zurück wenn einer der Kurse nicht bekannt ist.
    """
    fc = from_currency.upper()
    tc = to_currency.upper()

    if fc == tc:
        return round(amount, 2)

    # Direkter Kurs
    if fc in rates and tc in rates:
        # from → base → to
        rate = rates[tc] / rates[fc]
        return round(amount * rate, 2)

    logger.warning("Kurs %s→%s nicht verfügbar", fc, tc)
    return None


def format_rate(
    from_currency: str,
    to_currency: str,
    rates: dict[str, float],
) -> str:
    """Lesbare Kursanzeige, z.B. '1 USD = 0.9234 EUR'."""
    result = convert(1.0, from_currency, to_currency, rates)
    if result is None:
        return f"{from_currency} → {to_currency}: unbekannt"
    return f"1 {from_currency} = {result:.4f} {to_currency}"
