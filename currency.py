# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Currency Module

Exchange rates are fetched from a free API and cached locally
in SQLite. In offline mode the last known rates are used.

Refresh strategy: randomized intervals
  - Base interval: 6 hours
  - Jitter: +/- 0-3 hours (random)
  -> Prevents all nodes from querying the API simultaneously

API: open.er-api.com - free, no API key required.
Fallback: exchangerate-api.com (if primary API unreachable)
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

# All commonly supported currencies
SUPPORTED_CURRENCIES = [
    "EUR", "USD", "GBP", "CHF", "JPY", "CNY", "CAD", "AUD",
    "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN",
    "TRY", "BRL", "MXN", "INR", "KRW", "SGD", "HKD", "NZD",
]

# Refresh interval
_BASE_INTERVAL_SEC  = 6 * 3600   # 6 hour base
_MAX_JITTER_SEC     = 3 * 3600   # +/- 3 hour jitter

_API_URLS = [
    "https://open.er-api.com/v6/latest/{base}",
    "https://api.exchangerate-api.com/v4/latest/{base}",
]


# ---------------------------------------------------------------------------
# Schema (included by storage.init_db())
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
    """Next fetch time with random jitter."""
    jitter = random.randint(0, _MAX_JITTER_SEC)
    return int(time.time()) + _BASE_INTERVAL_SEC + jitter


def fetch_rates_online(base: str) -> Optional[dict[str, float]]:
    """
    Fetches current rates from the API.
    Returns a dict {target: rate} or None on error.
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
                logger.info("Rates for %s fetched from %s (%d target currencies)",
                            base, url, len(rates))
                return {k.upper(): float(v) for k, v in rates.items()}
        except urllib.error.URLError as e:
            logger.warning("API %s unreachable: %s", url, e)
        except Exception as e:
            logger.warning("Error fetching rates from %s: %s", url, e)

    logger.error("All APIs failed - staying offline")
    return None


# ---------------------------------------------------------------------------
# Cache (SQLite)
# ---------------------------------------------------------------------------

def save_rates(db: sqlite3.Connection, base: str, rates: dict[str, float]) -> None:
    """Saves exchange rates to the database."""
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
    logger.debug("Rates for %s saved (next fetch ~%s)",
                 base, time.strftime("%H:%M", time.localtime(next_time)))


def load_rates(db: sqlite3.Connection, base: str) -> dict[str, float]:
    """Loads cached exchange rates from the database."""
    rows = db.execute(
        "SELECT target, rate FROM exchange_rates WHERE base = ?",
        (base.upper(),),
    ).fetchall()
    return {r["target"]: r["rate"] for r in rows}


def rates_need_refresh(db: sqlite3.Connection, base: str) -> bool:
    """True if cached rates are stale or missing."""
    row = db.execute(
        "SELECT MIN(next_fetch) as nf FROM exchange_rates WHERE base = ?",
        (base.upper(),),
    ).fetchone()
    if not row or row["nf"] is None:
        return True
    return time.time() >= row["nf"]


def rates_age_str(db: sqlite3.Connection, base: str) -> str:
    """Human-readable age of cached rates, e.g. '2h 14m ago'."""
    row = db.execute(
        "SELECT MAX(fetched_at) as fa FROM exchange_rates WHERE base = ?",
        (base.upper(),),
    ).fetchone()
    if not row or row["fa"] is None:
        return "never updated"
    age = int(time.time()) - row["fa"]
    if age < 60:
        return "just now"
    if age < 3600:
        return f"vor {age // 60}m"
    h, m = divmod(age // 60, 60)
    return f"vor {h}h {m}m" if m else f"vor {h}h"


# ---------------------------------------------------------------------------
# High-level: Kurse holen (Cache oder Online)
# ---------------------------------------------------------------------------

def get_rates(db: sqlite3.Connection, base: str) -> dict[str, float]:
    """
    Returns current exchange rates.
    Fetches online if cache is stale/empty, otherwise uses cache.
    Falls back to cache if online fetch fails.
    """
    base = base.upper()
    if rates_need_refresh(db, base):
        logger.info("Rates for %s stale - fetching online...", base)
        fresh = fetch_rates_online(base)
        if fresh:
            save_rates(db, base, fresh)
            return fresh
        else:
            logger.warning("Online fetch failed - using cache")

    cached = load_rates(db, base)
    if cached:
        return cached

    logger.error("No rates for %s available (neither online nor cache)", base)
    return {}


def force_refresh(db: sqlite3.Connection, base: str) -> bool:
    """
    Forces an immediate online fetch.
    Returns True if successful.
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
    Converts an amount between two currencies.

    rates must be relative to a base currency
    (i.e. rates["EUR"] = EUR/base rate).

    Returns None if either rate is unknown.
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

    logger.warning("Rate %s->%s not available", fc, tc)
    return None


def format_rate(
    from_currency: str,
    to_currency: str,
    rates: dict[str, float],
) -> str:
    """Human-readable rate display, e.g. '1 USD = 0.9234 EUR'."""
    result = convert(1.0, from_currency, to_currency, rates)
    if result is None:
        return f"{from_currency} -> {to_currency}: unknown"
    return f"1 {from_currency} = {result:.4f} {to_currency}"
