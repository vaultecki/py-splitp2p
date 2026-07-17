from models import (
    Attachment,
    Expense,
    Settlement,
    Split,
    User,
    UserComment,
    format_amount,
    from_minor,
    split_by_percent,
    split_custom,
    split_equally,
    to_minor,
)


def test_to_minor_from_minor_roundtrip_eur():
    assert to_minor(12.50, "EUR") == 1250
    assert from_minor(1250, "EUR") == 12.5


def test_to_minor_jpy_has_zero_precision():
    assert to_minor(1500, "JPY") == 1500
    assert from_minor(1500, "JPY") == 1500.0


def test_format_amount():
    assert format_amount(1250, "EUR") == "12.50"
    assert format_amount(1500, "JPY") == "1500"


def test_split_equally_exact_division():
    splits = split_equally("exp1", 1000, "alice", ["alice", "bob"])
    assert [s.amount for s in splits] == [500, 500]
    assert all(s.belongs_to == "exp1" for s in splits)
    assert all(s.payer_key == "alice" for s in splits)


def test_split_equally_remainder_goes_to_first_debtor():
    splits = split_equally("exp1", 100, "alice", ["alice", "bob", "carol"])
    amounts = [s.amount for s in splits]
    assert sum(amounts) == 100
    assert amounts[0] == 34  # 100 // 3 = 33, remainder 1 -> first gets 34
    assert amounts[1] == 33
    assert amounts[2] == 33


def test_split_equally_no_debtors_returns_empty():
    assert split_equally("exp1", 100, "alice", []) == []


def test_split_custom():
    splits = split_custom("exp1", "alice", {"alice": 200, "bob": 800})
    by_debtor = {s.debtor_key: s.amount for s in splits}
    assert by_debtor == {"alice": 200, "bob": 800}


def test_split_by_percent_sums_to_total_amount():
    splits = split_by_percent("exp1", "alice", 100, {"alice": 50.0, "bob": 50.0})
    assert sum(s.amount for s in splits) == 100
    assert {s.amount for s in splits} == {50}


def test_split_by_percent_normalizes_when_not_100():
    # 25/25 -> effectively 50/50 of the total amount
    splits = split_by_percent("exp1", "alice", 100, {"alice": 25.0, "bob": 25.0})
    assert sum(s.amount for s in splits) == 100
    amounts = sorted(s.amount for s in splits)
    assert amounts == [50, 50]


def test_split_by_percent_handles_rounding_remainder():
    splits = split_by_percent("exp1", "alice", 100, {"a": 33.3, "b": 33.3, "c": 33.4})
    assert sum(s.amount for s in splits) == 100


def test_split_by_percent_empty_or_zero_returns_empty():
    assert split_by_percent("exp1", "alice", 100, {}) == []
    assert split_by_percent("exp1", "alice", 100, {"a": 0.0, "b": 0.0}) == []


def test_expense_wire_dict_roundtrip():
    exp = Expense.create(
        group_id="g1",
        description="Dinner",
        amount=1500,
        author_pubkey="alice",
        category="Food & Drink",
    )
    exp.splits = split_equally(exp.id, exp.amount, "alice", ["alice", "bob"])
    restored = Expense.from_wire_dict(exp.to_wire_dict())
    assert restored.id == exp.id
    assert restored.amount == exp.amount
    assert restored.description == exp.description
    assert len(restored.splits) == 2
    assert restored.splits[0].amount == exp.splits[0].amount


def test_settlement_wire_dict_roundtrip():
    s = Settlement.create(
        group_id="g1", from_key="bob", to_key="alice", amount=500, author_pubkey="bob"
    )
    restored = Settlement.from_wire_dict(s.to_wire_dict())
    assert restored.from_key == "bob"
    assert restored.to_key == "alice"
    assert restored.amount == 500


def test_settlement_note_roundtrips_through_wire_dict():
    s = Settlement.create(
        group_id="g1",
        from_key="bob",
        to_key="alice",
        amount=500,
        author_pubkey="bob",
        note="for the taxi",
    )
    restored = Settlement.from_wire_dict(s.to_wire_dict())
    assert restored.note == "for the taxi"


def test_settlement_note_defaults_to_none():
    s = Settlement.create(
        group_id="g1", from_key="bob", to_key="alice", amount=500, author_pubkey="bob"
    )
    assert s.note is None
    restored = Settlement.from_wire_dict(s.to_wire_dict())
    assert restored.note is None


def test_user_wire_dict_roundtrip():
    u = User.create(public_key="pk1", name="Alice", group_id="g1")
    restored = User.from_wire_dict(u.to_wire_dict())
    assert restored.public_key == "pk1"
    assert restored.name == "Alice"


def test_comment_wire_dict_roundtrip():
    c = UserComment.create(belongs_to="e1", comment="thanks!", author_pubkey="alice")
    restored = UserComment.from_wire_dict(c.to_wire_dict())
    assert restored.comment == "thanks!"
    assert restored.belongs_to == "e1"


def test_attachment_wire_dict_roundtrip_resets_is_stored():
    a = Attachment.create(
        belongs_to="e1", sha256="deadbeef", filename="receipt.png", author_pubkey="alice"
    )
    assert a.is_stored == 1  # ATTACHMENT_STORED after local create()
    restored = Attachment.from_wire_dict(a.to_wire_dict())
    assert restored.is_stored == 0  # ATTACHMENT_NOT_STORED — always reset on receive
    assert restored.sha256 == "deadbeef"


def test_split_wire_dict_roundtrip():
    s = Split.create(
        belongs_to="e1", payer_key="alice", debtor_key="bob", amount=500, author_pubkey="alice"
    )
    restored = Split.from_wire_dict(s.to_wire_dict())
    assert restored.debtor_key == "bob"
    assert restored.amount == 500
