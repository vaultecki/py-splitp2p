# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Data Models

All domain objects as dataclasses, JSON-serializable.
"""

from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Currency precision (decimal places for smallest unit)
# ---------------------------------------------------------------------------

# Maps currency code -> number of decimal places in the smallest unit.
# EUR: 1 euro = 100 cents -> precision 2 -> store as cents (integer)
# JPY: no subunit -> precision 0 -> store as yen (integer)
CURRENCY_PRECISION: dict[str, int] = {
    "EUR": 2, "USD": 2, "GBP": 2, "CHF": 2, "CAD": 2, "AUD": 2,
    "NZD": 2, "SGD": 2, "HKD": 2, "CNY": 2, "INR": 2, "BRL": 2,
    "MXN": 2, "PLN": 2, "CZK": 2, "RON": 2, "BGN": 2, "TRY": 2,
    "SEK": 2, "NOK": 2, "DKK": 2, "HUF": 2,
    "JPY": 0, "KRW": 0, "ISK": 0,
}


def currency_precision(currency: str) -> int:
    """Returns decimal places for the given currency (default 2)."""
    return CURRENCY_PRECISION.get(currency.upper(), 2)


def to_minor(amount: float, currency: str) -> int:
    """
    Converts a decimal amount to the smallest currency unit (integer).
    Example: to_minor(12.50, 'EUR') -> 1250  (cents)
             to_minor(1500, 'JPY') -> 1500  (yen, precision 0)
    """
    prec = currency_precision(currency)
    return round(amount * 10 ** prec)


def from_minor(amount: int, currency: str) -> float:
    """
    Converts a smallest-unit integer back to decimal.
    Example: from_minor(1250, 'EUR') -> 12.5
    """
    prec = currency_precision(currency)
    if prec == 0:
        return float(amount)
    return amount / 10 ** prec


def format_amount(amount: int, currency: str) -> str:
    """Human-readable amount string. format_amount(1250, 'EUR') -> '12.50'"""
    prec = currency_precision(currency)
    if prec == 0:
        return str(amount)
    return f"{amount / 10**prec:.{prec}f}"


# ---------------------------------------------------------------------------
# Kategorien
# ---------------------------------------------------------------------------

CATEGORIES: list[str] = [
    "Allgemein",
    "Essen & Trinken",
    "Transport",
    "Unterkunft",
    "Einkaufen",
    "Freizeit",
    "Gesundheit",
    "Reisen",
    "Sport",
    "Sonstiges",
]


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------

@dataclass
class Member:
    pubkey: str
    display_name: str
    joined_at: int = field(default_factory=lambda: int(time.time()))

    def short_key(self) -> str:
        return self.pubkey[:8] + "…"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Member":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------

@dataclass
class Attachment:
    sha256: str
    filename: str
    size: int
    mime_type: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Attachment":
        return cls(**d)

    def is_image(self) -> bool:
        return self.mime_type.startswith("image/")

    def is_pdf(self) -> bool:
        return self.mime_type == "application/pdf"

    def size_str(self) -> str:
        if self.size < 1024:
            return f"{self.size} B"
        if self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        return f"{self.size / (1024*1024):.1f} MB"


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

@dataclass
class Split:
    pubkey: str
    amount: int  # smallest currency unit

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Split":
        return cls(**d)


# ---------------------------------------------------------------------------
# Expense
# ---------------------------------------------------------------------------

@dataclass
class Expense:
    """
    An expense entry.

    CRDT merge priority (Lamport + tiebreaker):
      1. lamport_clock  - causality-based, clock-drift-independent
      2. timestamp      - wall clock tiebreaker for equal Lamport values
      3. payer_pubkey   - deterministic final tiebreaker (lexicographic)
    timestamp   : wall clock - display + tiebreaker only
    expense_date: user-chosen display date - Unix day start (UTC)
                  0 = not set -> timestamp is shown
    """
    id: str
    description: str
    amount: int            # smallest currency unit (e.g. cents for EUR)
    currency: str
    payer_pubkey: str
    splits: list[Split]
    timestamp: int
    signature: str
    lamport_clock: int = 0     # Lamport clock - primary CRDT ordering
    category: str = "Allgemein"
    expense_date: int = 0          # User-chosen display date, UTC midnight
    is_deleted: bool = False
    note: str = ""
    attachment: Optional[Attachment] = None
    original_amount: Optional[float] = None
    original_currency: Optional[str] = None

    def display_date(self) -> int:
        """Display date: expense_date if set, otherwise timestamp."""
        return self.expense_date if self.expense_date else self.timestamp

    @classmethod
    def create(
        cls,
        description: str,
        amount: int,
        currency: str,
        payer_pubkey: str,
        splits: list[Split],
        category: str = "Allgemein",
        expense_date: int = 0,
        note: str = "",
        attachment: Optional[Attachment] = None,
        original_amount: Optional[float] = None,
        original_currency: Optional[str] = None,
        lamport_clock: int = 0,
    ) -> "Expense":
        return cls(
            id=str(uuid.uuid4()),
            description=description,
            amount=int(amount),
            currency=currency,
            payer_pubkey=payer_pubkey,
            splits=splits,
            timestamp=int(time.time()),
            signature="",
            category=category,
            expense_date=expense_date,
            note=note,
            attachment=attachment,
            original_amount=original_amount,
            original_currency=original_currency,
            lamport_clock=lamport_clock,
        )

    def canonical_bytes(self) -> bytes:
        d = {
            "id": self.id,
            "description": self.description,
            "amount": str(self.amount),
            "currency": self.currency,
            "payer_pubkey": self.payer_pubkey,
            "splits": sorted(
                [{"pubkey": s.pubkey, "amount": str(s.amount)} for s in self.splits],
                key=lambda x: x["pubkey"],
            ),
            "timestamp": self.timestamp,
            "is_deleted": self.is_deleted,
            "attachment_sha256": self.attachment.sha256 if self.attachment else None,
        }
        return json.dumps(d, sort_keys=True, ensure_ascii=False).encode()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Expense":
        d = dict(d)
        splits = [Split.from_dict(s) for s in d.pop("splits")]
        att_raw = d.pop("attachment", None)
        attachment = Attachment.from_dict(att_raw) if att_raw else None
        # Forward-compat: ignore unknown fields
        known = cls.__dataclass_fields__.keys()
        d = {k: v for k, v in d.items() if k in known}
        return cls(splits=splits, attachment=attachment, **d)

    def validate_splits(self, tolerance: float = 0.02) -> bool:
        return abs(sum(s.amount for s in self.splits) - self.amount) <= tolerance

    def __repr__(self) -> str:
        return f"Expense('{self.description}', {self.amount} {self.currency})"


# ---------------------------------------------------------------------------
# RecordedSettlement  -  eine tatsaechlich geleistete Ausgleichszahlung
# ---------------------------------------------------------------------------

@dataclass
class RecordedSettlement:
    """
    Records that `from_pubkey` paid `to_pubkey` an amount.

    Difference from computed Settlement (ledger.py):
      - This class is persisted + signed + CRDT-synchronized.
      - The computed settlement is only a suggestion.

    CRDT: same id, increasing timestamp -> last-write-wins.
    """
    id: str
    from_pubkey: str    # who paid
    to_pubkey: str      # to whom
    amount: int         # smallest currency unit
    currency: str
    timestamp: int      # wall clock
    signature: str      # Ed25519 over canonical_bytes(), signed by from_pubkey
    lamport_clock: int = 0     # Lamport clock - primary CRDT ordering
    settlement_date: int = 0   # display date (UTC day start), 0 = use timestamp
    is_deleted: bool = False
    note: str = ""
    original_amount: Optional[float] = None
    original_currency: Optional[str] = None

    def display_date(self) -> int:
        return self.settlement_date if self.settlement_date else self.timestamp

    @classmethod
    def create(
        cls,
        from_pubkey: str,
        to_pubkey: str,
        amount: float,
        currency: str,
        settlement_date: int = 0,
        note: str = "",
        original_amount: Optional[float] = None,
        original_currency: Optional[str] = None,
    ) -> "RecordedSettlement":
        return cls(
            id=str(uuid.uuid4()),
            from_pubkey=from_pubkey,
            to_pubkey=to_pubkey,
            amount=int(amount),
            currency=currency,
            timestamp=int(time.time()),
            signature="",
            lamport_clock=0,  # set in gui.py before saving
            settlement_date=settlement_date,
            note=note,
            original_amount=original_amount,
            original_currency=original_currency,
        )

    def canonical_bytes(self) -> bytes:
        d = {
            "id": self.id,
            "from_pubkey": self.from_pubkey,
            "to_pubkey": self.to_pubkey,
            "amount": str(self.amount),
            "currency": self.currency,
            "timestamp": self.timestamp,
            "is_deleted": self.is_deleted,
        }
        return json.dumps(d, sort_keys=True, ensure_ascii=False).encode()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RecordedSettlement":
        d = dict(d)
        known = cls.__dataclass_fields__.keys()
        d = {k: v for k, v in d.items() if k in known}
        return cls(**d)

    def __repr__(self) -> str:
        return (f"RecordedSettlement({self.from_pubkey[:8]}->"
                f"{self.to_pubkey[:8]}, {self.amount} {self.currency})")


# ---------------------------------------------------------------------------
# Split-Hilfsfunktionen
# ---------------------------------------------------------------------------

def split_equally(amount: int, pubkeys: list[str]) -> list[Split]:
    """Splits an integer (minor unit) amount equally. Remainder goes to first."""
    n = len(pubkeys)
    if n == 0:
        return []
    share = amount // n
    remainder = amount - share * n
    splits = [Split(pubkey=pk, amount=share) for pk in pubkeys]
    if remainder:
        splits[0] = Split(splits[0].pubkey, splits[0].amount + remainder)
    return splits


def split_custom(amounts_by_pubkey: dict[str, int]) -> list[Split]:
    """Creates splits from a dict of pubkey -> minor-unit amounts."""
    return [Split(pubkey=pk, amount=int(amt)) for pk, amt in amounts_by_pubkey.items()]


def split_by_percent(amount: int,
                     percentages_by_pubkey: dict[str, float]) -> list[Split]:
    """
    Split an amount by percentages.

    Args:
        amount: total amount
        percentages_by_pubkey: {pubkey: percent} - should sum to 100.
            If the sum differs, values are scaled proportionally.

    Returns:
        List of splits in absolute amounts.
        Rounding difference is added to the first entry.
    """
    if not percentages_by_pubkey:
        return []
    total_pct = sum(percentages_by_pubkey.values())
    if total_pct <= 0:
        return []
    # Normalize if sum != 100
    scale = 100.0 / total_pct
    splits = [
        Split(pubkey=pk, amount=round(amount * (pct * scale) / 100.0))
        for pk, pct in percentages_by_pubkey.items()
    ]
    # Integer rounding: distribute remainder to first entry
    diff = amount - sum(s.amount for s in splits)
    if diff:
        splits[0] = Split(splits[0].pubkey, splits[0].amount + diff)
    return splits


# ---------------------------------------------------------------------------
# Comment  -  per-expense comment or auto-generated change log entry
# ---------------------------------------------------------------------------

@dataclass
class Comment:
    """
    A comment attached to an expense.

    Two kinds:
      kind="user"   - written by a group member
      kind="system" - auto-generated when an expense is edited or deleted
                      (e.g. "Amount changed from 10.00 to 12.00 EUR")

    CRDT: same id, higher lamport_clock wins (last-write-wins).
    Encrypted as AES-256-GCM blob with the group key; signed by author.
    """
    id: str
    expense_id: str          # foreign key -> Expense.id
    author_pubkey: str       # who wrote / who triggered the system event
    text: str                # comment body
    timestamp: int           # wall clock (display only)
    signature: str           # Ed25519 over canonical_bytes()
    lamport_clock: int = 0
    kind: str = "user"       # "user" | "system"
    is_deleted: bool = False

    def display_time(self) -> str:
        import time as _t
        return _t.strftime("%d.%m.%Y %H:%M", _t.localtime(self.timestamp))

    def canonical_bytes(self) -> bytes:
        d = {
            "id":           self.id,
            "expense_id":   self.expense_id,
            "author_pubkey":self.author_pubkey,
            "text":         self.text,
            "timestamp":    self.timestamp,
            "kind":         self.kind,
            "is_deleted":   self.is_deleted,
        }
        return json.dumps(d, sort_keys=True, ensure_ascii=False).encode()

    @classmethod
    def create(cls, expense_id: str, author_pubkey: str,
               text: str, kind: str = "user") -> "Comment":
        return cls(
            id=str(uuid.uuid4()),
            expense_id=expense_id,
            author_pubkey=author_pubkey,
            text=text,
            timestamp=int(time.time()),
            signature="",
            lamport_clock=0,
            kind=kind,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Comment":
        d = dict(d)
        known = cls.__dataclass_fields__.keys()
        d = {k: v for k, v in d.items() if k in known}
        return cls(**d)

    def __repr__(self) -> str:
        return f"Comment({self.author_pubkey[:8]}... on {self.expense_id[:8]}...)"
