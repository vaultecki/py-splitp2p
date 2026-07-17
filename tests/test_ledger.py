from dataclasses import dataclass, field

from ledger import (
    balance_summary,
    compute_balances,
    compute_settlements,
    ledger_cache_key,
)


@dataclass
class FakeSplit:
    debtor_key: str
    amount: int


@dataclass
class FakeExpense:
    id: str
    author_pubkey: str
    amount: int
    splits: list = field(default_factory=list)
    is_deleted: int = 0
    timestamp: int = 0
    lamport_clock: int = 0


@dataclass
class FakeSettlement:
    id: str
    from_key: str
    to_key: str
    amount: int
    is_deleted: int = 0
    timestamp: int = 0
    lamport_clock: int = 0


def make_expense(payer, shares: dict, amount=None, **kw):
    amount = amount if amount is not None else sum(shares.values())
    exp = FakeExpense(id="e1", author_pubkey=payer, amount=amount, **kw)
    exp.splits = [FakeSplit(debtor_key=k, amount=v) for k, v in shares.items()]
    return exp


def test_compute_balances_single_expense_split_two_ways():
    # Alice pays 1000, split equally between Alice and Bob (500 each)
    exp = make_expense("alice", {"alice": 500, "bob": 500}, amount=1000)
    bal = compute_balances([exp])
    assert bal["alice"] == 500  # paid 1000, owes 500 -> net +500
    assert bal["bob"] == -500  # owes 500, paid nothing -> net -500


def test_compute_balances_ignores_deleted_expenses():
    exp = make_expense("alice", {"alice": 500, "bob": 500}, amount=1000, is_deleted=1)
    bal = compute_balances([exp])
    assert bal == {}


def test_compute_balances_settlement_reduces_debt():
    exp = make_expense("alice", {"alice": 500, "bob": 500}, amount=1000)
    settlement = FakeSettlement(id="s1", from_key="bob", to_key="alice", amount=500)
    bal = compute_balances([exp], [settlement])
    assert bal["alice"] == 0
    assert bal["bob"] == 0


def test_compute_balances_ignores_deleted_settlements():
    exp = make_expense("alice", {"alice": 500, "bob": 500}, amount=1000)
    settlement = FakeSettlement(id="s1", from_key="bob", to_key="alice", amount=500, is_deleted=1)
    bal = compute_balances([exp], [settlement])
    assert bal["alice"] == 500
    assert bal["bob"] == -500


def test_balance_summary():
    balances = {"me": 300, "alice": -100, "bob": -200}
    summary = balance_summary("me", balances)
    # owes_total/owed_total summarize *everyone else's* balances, not a
    # pairwise relation to "me" — alice+bob's combined debt is 300, nobody
    # else is in credit.
    assert summary == {"net": 300, "owes_total": 300, "owed_total": 0}

    # From alice's perspective: she owes 100, is owed nothing else relevant
    summary_alice = balance_summary("alice", balances)
    assert summary_alice["net"] == -100
    assert summary_alice["owed_total"] == 300  # "me" is owed 300
    assert summary_alice["owes_total"] == 200  # "bob" owes 200


def test_compute_settlements_minimizes_transfers():
    # alice owed 700, bob owes 300, carol owes 400
    balances = {"alice": 700, "bob": -300, "carol": -400}
    settlements = compute_settlements(balances)
    assert len(settlements) == 2
    total_to_alice = sum(s.amount for s in settlements if s.creditor == "alice")
    assert total_to_alice == 700
    for s in settlements:
        assert s.debtor in ("bob", "carol")
        assert s.creditor == "alice"


def test_compute_settlements_empty_when_balanced():
    assert compute_settlements({"alice": 0, "bob": 0}) == []


def test_compute_settlements_odd_remainder_split():
    # Classic case: 3-way equal split of an odd amount, one owed, two owe
    balances = {"alice": 2, "bob": -1, "carol": -1}
    settlements = compute_settlements(balances)
    assert sum(s.amount for s in settlements) == 2
    assert all(s.creditor == "alice" for s in settlements)


def test_ledger_cache_key_changes_when_state_changes():
    exp1 = make_expense("alice", {"alice": 500, "bob": 500}, amount=1000, timestamp=1)
    key1 = ledger_cache_key([exp1])
    exp1.lamport_clock = 5
    key2 = ledger_cache_key([exp1])
    assert key1 != key2


def test_ledger_cache_key_stable_for_same_state():
    exp1 = make_expense("alice", {"alice": 500, "bob": 500}, amount=1000, timestamp=1)
    exp2 = make_expense("alice", {"alice": 500, "bob": 500}, amount=1000, timestamp=1)
    exp2.id = exp1.id
    assert ledger_cache_key([exp1]) == ledger_cache_key([exp2])
