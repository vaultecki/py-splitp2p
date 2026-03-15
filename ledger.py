# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Ledger Module – Debt and balance calculation.

compute_balances()   accounts for expenses AND already recorded payments.
compute_settlements() minimizes remaining open amounts (greedy).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence, Optional

from models import Expense, RecordedSettlement, Member


# ---------------------------------------------------------------------------
# Cache-Key
# ---------------------------------------------------------------------------

def ledger_cache_key(
        expenses: Sequence[Expense],
        recorded: Sequence[RecordedSettlement] = (),
) -> int:
    """
    Schneller Cache key for the current ledger state.

    Computes a hash over (id, timestamp, is_deleted) of all entries.
    Changes if and only if the content changes.
    Uses Python's built-in hash() - sufficient for in-process caching.
    """
    return hash(tuple(
        (e.id, e.timestamp, e.is_deleted, e.lamport_clock) for e in expenses
    ) + tuple(
        (s.id, s.timestamp, s.is_deleted, s.lamport_clock) for s in recorded
    ))


# ---------------------------------------------------------------------------
# Saldo-Berechnung
# ---------------------------------------------------------------------------

def compute_balances(
    expenses: Sequence[Expense],
    recorded: Sequence[RecordedSettlement] = (),
) -> dict[str, float]:
    """
    Net balance per person.

    Positive balance -> person is owed money.
    Negative balance -> person owes money.

    Recorded settlements reduce open amounts:
      from_pubkey paid -> debt decreases -> balance increases
      to_pubkey received -> credit decreases -> balance decreases
    """
    balances: dict[str, float] = {}

    for exp in expenses:
        if exp.is_deleted:
            continue
        balances[exp.payer_pubkey] = balances.get(exp.payer_pubkey, 0.0) + exp.amount
        for split in exp.splits:
            balances[split.pubkey] = balances.get(split.pubkey, 0.0) - split.amount

    for rs in recorded:
        if rs.is_deleted:
            continue
        balances[rs.from_pubkey] = balances.get(rs.from_pubkey, 0.0) + rs.amount
        balances[rs.to_pubkey]   = balances.get(rs.to_pubkey,   0.0) - rs.amount

    return {pk: round(bal, 2) for pk, bal in balances.items()}


def balance_summary(
    own_pubkey: str,
    balances: dict[str, float],
) -> dict:
    """
    Summary for the sidebar:
      owes_total    - sum of amounts I owe others
      owed_total    - sum of amounts others owe me
      net           - net balance (positive = owed to me, negative = I owe)
    """
    net = balances.get(own_pubkey, 0.0)
    owes  = sum(-b for pk, b in balances.items() if pk != own_pubkey and b < -0.005)
    owed  = sum( b for pk, b in balances.items() if pk != own_pubkey and b >  0.005)
    return {"net": net, "owes_total": round(owes, 2), "owed_total": round(owed, 2)}


# ---------------------------------------------------------------------------
# Schulden minimieren (berechnete Vorschläge)
# ---------------------------------------------------------------------------

@dataclass
class Settlement:
    """Suggested settlement transfer (not persistent - display only)."""
    debtor:   str    # pubkey - who should pay
    creditor: str    # pubkey - who should receive
    amount:   float

    def __repr__(self) -> str:
        return f"{self.debtor[:8]}…→{self.creditor[:8]}… {self.amount:.2f}"


def compute_settlements(balances: dict[str, float]) -> list[Settlement]:
    """Greedy: minimizes number of required transfers."""
    debtors  = sorted([(pk, -b) for pk, b in balances.items() if b < -0.005],
                      key=lambda x: -x[1])
    creditors = sorted([(pk,  b) for pk, b in balances.items() if b >  0.005],
                       key=lambda x: -x[1])
    result: list[Settlement] = []
    d_i = c_i = 0
    while d_i < len(debtors) and c_i < len(creditors):
        d_pk, d_amt = debtors[d_i]
        c_pk, c_amt = creditors[c_i]
        pay = round(min(d_amt, c_amt), 2)
        if pay > 0:
            result.append(Settlement(debtor=d_pk, creditor=c_pk, amount=pay))
        d_amt = round(d_amt - pay, 2)
        c_amt = round(c_amt - pay, 2)
        if d_amt < 0.005: d_i += 1
        else: debtors[d_i] = (d_pk, d_amt)
        if c_amt < 0.005: c_i += 1
        else: creditors[c_i] = (c_pk, c_amt)
    return result


def get_settlements(
    expenses: Sequence[Expense],
    recorded: Sequence[RecordedSettlement] = (),
) -> list[Settlement]:
    return compute_settlements(compute_balances(expenses, recorded))


def describe_settlements(
    settlements: list[Settlement],
    members: list[Member],
) -> list[str]:
    pk_to_name = {m.pubkey: m.display_name for m in members}
    def name(pk): return pk_to_name.get(pk, pk[:8] + "…")
    return [f"{name(s.debtor)} schuldet {name(s.creditor)} {s.amount:.2f}"
            for s in settlements]
