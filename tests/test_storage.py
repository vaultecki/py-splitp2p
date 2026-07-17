import pytest

import storage


@pytest.fixture
def db():
    conn = storage.init_db(":memory:")
    yield conn
    conn.close()


def test_init_db_creates_expected_tables(db):
    tables = {
        r["name"]
        for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {
        "group_info",
        "users",
        "expenses",
        "split",
        "settlements",
        "comments_user",
        "comments_system",
        "attachments",
        "exchange_rates",
    }.issubset(tables)


def test_group_info_save_and_get(db):
    storage.save_group_info(db, "g1", "Trip", "EUR", b"0" * 32)
    row = storage.get_group_info(db, "g1")
    assert row["name"] == "Trip"
    assert row["currency"] == "EUR"
    assert storage.get_group_key(db, "g1") == b"0" * 32


def test_get_group_key_missing_group_returns_none(db):
    assert storage.get_group_key(db, "nonexistent") is None


def test_save_user_insert_and_update(db):
    ok = storage.save_user(
        db,
        group_id="g1",
        public_key="pk1",
        name="Alice",
        timestamp=100,
        lamport_clock=1,
        signature="sig1",
    )
    assert ok is True
    row = storage.get_user(db, "pk1", "g1")
    assert row["name"] == "Alice"

    # Newer lamport_clock wins
    ok2 = storage.save_user(
        db,
        group_id="g1",
        public_key="pk1",
        name="Alice2",
        timestamp=101,
        lamport_clock=2,
        signature="sig2",
    )
    assert ok2 is True
    assert storage.get_user(db, "pk1", "g1")["name"] == "Alice2"


def test_save_user_rejects_stale_lamport_clock(db):
    storage.save_user(
        db,
        group_id="g1",
        public_key="pk1",
        name="Alice",
        timestamp=100,
        lamport_clock=5,
        signature="sig1",
    )
    ok = storage.save_user(
        db,
        group_id="g1",
        public_key="pk1",
        name="Stale",
        timestamp=200,
        lamport_clock=1,
        signature="sig-stale",
    )
    assert ok is False
    assert storage.get_user(db, "pk1", "g1")["name"] == "Alice"


def test_get_all_users_sorted_by_name(db):
    storage.save_user(
        db, group_id="g1", public_key="pk2", name="Zoe", timestamp=1, lamport_clock=1, signature=""
    )
    storage.save_user(
        db,
        group_id="g1",
        public_key="pk1",
        name="Alice",
        timestamp=1,
        lamport_clock=1,
        signature="",
    )
    names = [r["name"] for r in storage.get_all_users(db, "g1")]
    assert names == ["Alice", "Zoe"]


def _save_expense(db, **overrides):
    kwargs = {
        "id": "e1",
        "group_id": "g1",
        "timestamp": 100,
        "expense_date": 100,
        "lamport_clock": 1,
        "author_pubkey": "alice",
        "amount": 1000,
        "description": "Dinner",
        "signature": "sig",
    }
    kwargs.update(overrides)
    return storage.save_expense(db, **kwargs)


def test_save_and_get_expense(db):
    assert _save_expense(db) is True
    row = storage.get_expense(db, "e1")
    assert row["description"] == "Dinner"
    assert row["amount"] == 1000

    expenses = storage.get_expenses(db, "g1")
    assert len(expenses) == 1


def test_get_expenses_excludes_deleted_by_default(db):
    _save_expense(db)
    _save_expense(db, id="e2", is_deleted=1, lamport_clock=1)
    assert len(storage.get_expenses(db, "g1")) == 1
    assert len(storage.get_expenses(db, "g1", include_deleted=True)) == 2


def test_save_expense_crdt_tiebreak_by_author_pubkey(db):
    _save_expense(db, timestamp=100, lamport_clock=5, author_pubkey="bob")
    # Same lamport_clock and timestamp -> higher author_pubkey wins
    won = _save_expense(db, timestamp=100, lamport_clock=5, author_pubkey="zzz", description="New")
    assert won is True
    assert storage.get_expense(db, "e1")["description"] == "New"


def test_save_and_get_splits(db):
    _save_expense(db)
    splits = [
        {
            "id": "s1",
            "timestamp": 1,
            "lamport_clock": 1,
            "author_pubkey": "alice",
            "payer_key": "alice",
            "debtor_key": "bob",
            "amount": 500,
            "signature": "",
        }
    ]
    storage.save_splits(db, "e1", splits)
    rows = storage.get_splits(db, "e1")
    assert len(rows) == 1
    assert rows[0]["debtor_key"] == "bob"
    assert rows[0]["amount"] == 500


def test_save_splits_replaces_existing(db):
    _save_expense(db)
    storage.save_splits(
        db,
        "e1",
        [
            {
                "id": "s1",
                "timestamp": 1,
                "lamport_clock": 1,
                "author_pubkey": "a",
                "payer_key": "a",
                "debtor_key": "b",
                "amount": 100,
                "signature": "",
            }
        ],
    )
    storage.save_splits(
        db,
        "e1",
        [
            {
                "id": "s2",
                "timestamp": 2,
                "lamport_clock": 2,
                "author_pubkey": "a",
                "payer_key": "a",
                "debtor_key": "c",
                "amount": 200,
                "signature": "",
            }
        ],
    )
    rows = storage.get_splits(db, "e1")
    assert len(rows) == 1
    assert rows[0]["id"] == "s2"


def test_save_and_get_settlement(db):
    ok = storage.save_settlement(
        db,
        id="s1",
        group_id="g1",
        timestamp=1,
        lamport_clock=1,
        author_pubkey="bob",
        from_key="bob",
        to_key="alice",
        amount=500,
        signature="",
    )
    assert ok is True
    rows = storage.get_settlements(db, "g1")
    assert len(rows) == 1
    assert rows[0]["from_key"] == "bob"


def test_save_settlement_persists_note(db):
    storage.save_settlement(
        db,
        id="s1",
        group_id="g1",
        timestamp=1,
        lamport_clock=1,
        author_pubkey="bob",
        from_key="bob",
        to_key="alice",
        amount=500,
        note="for the taxi",
        signature="",
    )
    row = storage.get_settlements(db, "g1")[0]
    assert row["note"] == "for the taxi"


def test_save_settlement_persists_settlement_date(db):
    storage.save_settlement(
        db,
        id="s1",
        group_id="g1",
        timestamp=1,
        lamport_clock=1,
        author_pubkey="bob",
        from_key="bob",
        to_key="alice",
        amount=500,
        settlement_date=12345,
        signature="",
    )
    row = storage.get_settlements(db, "g1")[0]
    assert row["settlement_date"] == 12345


def test_save_comment_user_and_system_merged_sorted(db):
    storage.save_comment_user(
        db,
        id="c2",
        belongs_to="e1",
        timestamp=200,
        lamport_clock=1,
        author_pubkey="alice",
        comment="second",
        signature="",
    )
    storage.save_comment_system(db, id="c1", belongs_to="e1", timestamp=100, comment="created")
    comments = storage.get_comments(db, "e1")
    assert [c["comment"] for c in comments] == ["created", "second"]
    assert comments[0]["kind"] == "system"
    assert comments[1]["kind"] == "user"


def test_save_and_get_attachment(db):
    ok = storage.save_attachment(
        db,
        id="a1",
        belongs_to="e1",
        timestamp=1,
        lamport_clock=1,
        author_pubkey="alice",
        sha256="deadbeef",
        filename="r.png",
        mime="image/png",
        size=1234,
        signature="",
    )
    assert ok is True


def test_get_max_lamport_clock_empty_db_returns_zero(db):
    assert storage.get_max_lamport_clock(db) == 0


def test_get_max_lamport_clock_across_tables(db):
    storage.save_user(
        db,
        group_id="g1",
        public_key="pk1",
        name="Alice",
        timestamp=1,
        lamport_clock=3,
        signature="",
    )
    _save_expense(db, lamport_clock=7)
    storage.save_settlement(
        db,
        id="s1",
        group_id="g1",
        timestamp=1,
        lamport_clock=2,
        author_pubkey="bob",
        from_key="bob",
        to_key="alice",
        amount=100,
        signature="",
    )
    assert storage.get_max_lamport_clock(db) == 7
    assert storage.get_max_lamport_clock(db, "g1") == 7
    assert storage.get_max_lamport_clock(db, "other-group") == 0


def test_get_lamport_map(db):
    _save_expense(db, lamport_clock=4)
    lm = storage.get_lamport_map(db, "g1")
    assert lm["expenses"] == {"e1": 4}


def test_get_records_unknown_to_returns_newer_records(db):
    _save_expense(db, lamport_clock=4)
    delta = storage.get_records_unknown_to(db, {"expenses": {}}, "g1")
    assert len(delta["expenses"]) == 1
    delta_known = storage.get_records_unknown_to(db, {"expenses": {"e1": 4}}, "g1")
    assert len(delta_known["expenses"]) == 0


def test_wins_prefers_higher_lamport_clock():
    assert storage._wins(5, 100, 3, 200) is True
    assert storage._wins(3, 100, 5, 200) is False


def test_wins_tiebreaks_on_timestamp_then_author():
    assert storage._wins(5, 200, 5, 100) is True
    assert storage._wins(5, 100, 5, 100, "zzz", "aaa") is True
    assert storage._wins(5, 100, 5, 100, "aaa", "zzz") is False


def test_attachment_exists_and_path(tmp_path):
    storage.STORAGE_DIR = str(tmp_path)
    assert storage.attachment_exists("deadbeef") is False
    assert storage.attachment_path("deadbeef") is None

    (tmp_path / "deadbeef").write_bytes(b"file contents")
    assert storage.attachment_exists("deadbeef") is True
    assert storage.attachment_path("deadbeef") == str(tmp_path / "deadbeef")

    storage.STORAGE_DIR = ""


def test_attachment_exists_false_when_storage_dir_unset():
    storage.STORAGE_DIR = ""
    assert storage.attachment_exists("deadbeef") is False
