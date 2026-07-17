import json
import sqlite3
import time
from unittest.mock import patch

import pytest

import currency


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE exchange_rates (
            base        TEXT NOT NULL,
            target      TEXT NOT NULL,
            rate        REAL NOT NULL,
            fetched_at  INTEGER NOT NULL,
            next_fetch  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (base, target)
        );
        """
    )
    yield conn
    conn.close()


def test_convert_same_currency_returns_rounded_amount():
    assert currency.convert(12.345, "EUR", "EUR", {}) == 12.35


def test_convert_with_known_rates():
    rates = {"EUR": 1.0, "USD": 1.1}
    result = currency.convert(10, "EUR", "USD", rates)
    assert result == pytest.approx(11.0)


def test_convert_returns_none_when_rate_missing():
    assert currency.convert(10, "EUR", "XYZ", {"EUR": 1.0}) is None


def test_format_rate_known():
    rates = {"EUR": 1.0, "USD": 1.1}
    assert currency.format_rate("EUR", "USD", rates) == "1 EUR = 1.1000 USD"


def test_format_rate_unknown():
    assert currency.format_rate("EUR", "XYZ", {}) == "EUR -> XYZ: unknown"


def test_save_and_load_rates_roundtrip(db):
    currency.save_rates(db, "eur", {"usd": 1.1, "gbp": 0.85})
    loaded = currency.load_rates(db, "EUR")
    assert loaded == {"USD": 1.1, "GBP": 0.85}


def test_rates_need_refresh_true_when_empty(db):
    assert currency.rates_need_refresh(db, "EUR") is True


def test_rates_need_refresh_false_when_fresh(db):
    currency.save_rates(db, "EUR", {"USD": 1.1})
    assert currency.rates_need_refresh(db, "EUR") is False


def test_rates_need_refresh_true_when_stale(db):
    now = int(time.time())
    db.execute(
        "INSERT INTO exchange_rates(base,target,rate,fetched_at,next_fetch) VALUES(?,?,?,?,?)",
        ("EUR", "USD", 1.1, now - 100, now - 1),
    )
    db.commit()
    assert currency.rates_need_refresh(db, "EUR") is True


def _fake_response(payload: dict):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode()

    return _Resp()


def test_fetch_rates_online_parses_open_er_api_format():
    with patch("urllib.request.urlopen", return_value=_fake_response({"rates": {"usd": 1.1}})):
        rates = currency.fetch_rates_online("eur")
    assert rates == {"USD": 1.1}


def test_fetch_rates_online_returns_none_on_all_apis_failing():
    with patch("urllib.request.urlopen", side_effect=OSError("network down")):
        assert currency.fetch_rates_online("eur") is None


def test_get_rates_uses_cache_when_fresh(db):
    currency.save_rates(db, "EUR", {"USD": 1.1})
    with patch("currency.fetch_rates_online") as mock_fetch:
        rates = currency.get_rates(db, "EUR")
    mock_fetch.assert_not_called()
    assert rates == {"USD": 1.1}


def test_get_rates_falls_back_to_cache_on_fetch_failure(db):
    currency.save_rates(db, "EUR", {"USD": 1.1})
    # Force stale so get_rates attempts a fetch
    db.execute("UPDATE exchange_rates SET next_fetch=0")
    db.commit()
    with patch("currency.fetch_rates_online", return_value=None):
        rates = currency.get_rates(db, "EUR")
    assert rates == {"USD": 1.1}
