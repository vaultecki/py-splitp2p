# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Ledger — debt and balance calculation.

Works on model objects (Expense, Settlement) — not DB rows directly.
All amounts are integers in the smallest currency unit (e.g. cents for EUR).

compute_balances():   net balance per pubkey
compute_settlements(): minimize number of transfers (greedy)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def ledger_cache_key(expenses: Sequence, settlements: Sequence = ()) -> int:
    """Hash of current state. Recompute ledger only when this changes."""
    return hash(
        tuple((e.id, e.timestamp, e.is_deleted, e.lamport_clock)
              for e in expenses)
        + tuple((s.id, s.timestamp, s.is_deleted, s.lamport_clock)
                for s in settlements))


# ---------------------------------------------------------------------------
# Balance calculation
# ---------------------------------------------------------------------------

def compute_balances(expenses: Sequence,
                     settlements: Sequence = ()) -> dict[str, int]:
    """
    Net balance per pubkey in minor currency units.
      Positive = owed money (paid more than share)
      Negative = owes money (paid less than share)

    expenses:    Expense model objects with .splits (list of Split)
    settlements: Settlement model objects (recorded payments)
    """
    bal: dict[str, int] = {}

    for exp in expenses:
        if exp.is_deleted:
            continue
        # Payer gets credit for the full amount
        bal[exp.author_pubkey] = bal.get(exp.author_pubkey, 0) + exp.amount
        # Each debtor owes their share
        for s in exp.splits:
            bal[s.debtor_key] = bal.get(s.debtor_key, 0) - s.amount

    for s in settlements:
        if s.is_deleted:
            continue
        # from_key paid → their debt decreases
        bal[s.from_key] = bal.get(s.from_key, 0) + s.amount
        # to_key received → their credit decreases
        bal[s.to_key] = bal.get(s.to_key, 0) - s.amount

    return bal


def balance_summary(own_pubkey: str, balances: dict[str, int]) -> dict:
    """Summary for sidebar display."""
    net  = balances.get(own_pubkey, 0)
    owes = sum(-b for pk, b in balances.items() if pk != own_pubkey and b < 0)
    owed = sum( b for pk, b in balances.items() if pk != own_pubkey and b > 0)
    return {"net": net, "owes_total": owes, "owed_total": owed}


# ---------------------------------------------------------------------------
# Suggested settlements (display only, not persisted)
# ---------------------------------------------------------------------------

@dataclass
class SuggestedSettlement:
    """A suggested debt payment. Not stored — computed on the fly."""
    debtor:   str   # pubkey — should pay
    creditor: str   # pubkey — should receive
    amount:   int   # minor currency units


def compute_settlements(balances: dict[str, int]) -> list[SuggestedSettlement]:
    """Greedy: minimize number of transfers to settle all debts."""
    debtors   = sorted([(pk, -b) for pk, b in balances.items() if b < 0],
                       key=lambda x: -x[1])
    creditors = sorted([(pk,  b) for pk, b in balances.items() if b > 0],
                       key=lambda x: -x[1])
    result: list[SuggestedSettlement] = []
    d_i = c_i = 0
    while d_i < len(debtors) and c_i < len(creditors):
        d_pk, d_amt = debtors[d_i]
        c_pk, c_amt = creditors[c_i]
        pay = min(d_amt, c_amt)
        if pay > 0:
            result.append(SuggestedSettlement(d_pk, c_pk, pay))
        d_amt -= pay
        c_amt -= pay
        if d_amt == 0: d_i += 1
        else: debtors[d_i] = (d_pk, d_amt)
        if c_amt == 0: c_i += 1
        else: creditors[c_i] = (c_pk, c_amt)
    return result
