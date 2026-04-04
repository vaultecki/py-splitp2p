# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
models.py — Data models matching the normalized DB schema

Each model:
  - Maps 1:1 to a DB table row
  - Has canonical_bytes() for Ed25519 signing (no local-only fields)
  - Has to_wire_dict() for network transmission (no local-only fields)
  - Has from_wire_dict() classmethod for deserializing received records

Local-only fields excluded from canonical_bytes and to_wire_dict:
  - Attachment.is_stored

Wire format for network sync:
  Records are serialized via to_wire_dict(), JSON-encoded, then encrypted
  with the group SecretBox key before transmission. Received records are
  decrypted, signature verified, then saved via storage.save_*().
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Currency helpers
# ---------------------------------------------------------------------------

CURRENCY_PRECISION: dict[str, int] = {
    "EUR": 2, "USD": 2, "GBP": 2, "CHF": 2, "CAD": 2, "AUD": 2,
    "NZD": 2, "SGD": 2, "HKD": 2, "CNY": 2, "INR": 2, "BRL": 2,
    "MXN": 2, "PLN": 2, "CZK": 2, "RON": 2, "BGN": 2, "TRY": 2,
    "SEK": 2, "NOK": 2, "DKK": 2, "HUF": 2,
    "JPY": 0, "KRW": 0, "ISK": 0,
}

EXPENSE_CATEGORIES = [
    "Food & Drink", "Transport", "Accommodation", "Activities",
    "Shopping", "Health", "Other",
]


def currency_precision(currency: str) -> int:
    return CURRENCY_PRECISION.get(currency.upper(), 2)


def to_minor(amount: float, currency: str) -> int:
    """12.50 EUR → 1250 (cents)"""
    return round(amount * 10 ** currency_precision(currency))


def from_minor(amount: int, currency: str) -> float:
    """1250 → 12.5 (EUR)"""
    prec = currency_precision(currency)
    return float(amount) if prec == 0 else amount / 10 ** prec


def format_amount(amount: int, currency: str) -> str:
    """1250 EUR → '12.50'"""
    prec = currency_precision(currency)
    return str(amount) if prec == 0 else f"{amount / 10**prec:.{prec}f}"


# ---------------------------------------------------------------------------
# User (maps to users table)
# ---------------------------------------------------------------------------

@dataclass
class User:
    public_key:    str
    name:          str
    group_id:      str
    timestamp:     int
    lamport_clock: int
    signature:     str = ""

    def canonical_bytes(self) -> bytes:
        return (f"{self.public_key}|{self.group_id}|{self.name}"
                f"|{self.timestamp}|{self.lamport_clock}").encode()

    def to_wire_dict(self) -> dict:
        return {
            "public_key":    self.public_key,
            "name":          self.name,
            "group_id":      self.group_id,
            "timestamp":     self.timestamp,
            "lamport_clock": self.lamport_clock,
            "signature":     self.signature,
        }

    @classmethod
    def from_wire_dict(cls, d: dict) -> "User":
        return cls(
            public_key=d["public_key"], name=d["name"],
            group_id=d["group_id"], timestamp=d["timestamp"],
            lamport_clock=d["lamport_clock"], signature=d["signature"])

    @classmethod
    def create(cls, public_key: str, name: str, group_id: str,
               lamport_clock: int = 0) -> "User":
        return cls(public_key=public_key, name=name, group_id=group_id,
                   timestamp=int(time.time()), lamport_clock=lamport_clock)


# ---------------------------------------------------------------------------
# Split (child of Expense, maps to split table)
# ---------------------------------------------------------------------------

@dataclass
class Split:
    id:            str
    belongs_to:    str   # expense.id
    payer_key:     str   # who paid (= expense author)
    debtor_key:    str   # who owes
    amount:        int   # smallest currency unit
    author_pubkey: str
    timestamp:     int
    lamport_clock: int
    signature:     str = ""

    def canonical_bytes(self) -> bytes:
        return (f"{self.id}|{self.belongs_to}|{self.payer_key}"
                f"|{self.debtor_key}|{self.amount}"
                f"|{self.author_pubkey}|{self.timestamp}"
                f"|{self.lamport_clock}").encode()

    def to_wire_dict(self) -> dict:
        return {
            "id":            self.id,
            "belongs_to":    self.belongs_to,
            "payer_key":     self.payer_key,
            "debtor_key":    self.debtor_key,
            "amount":        self.amount,
            "author_pubkey": self.author_pubkey,
            "timestamp":     self.timestamp,
            "lamport_clock": self.lamport_clock,
            "signature":     self.signature,
        }

    @classmethod
    def from_wire_dict(cls, d: dict) -> "Split":
        return cls(**{k: d[k] for k in
                      ("id", "belongs_to", "payer_key", "debtor_key",
                       "amount", "author_pubkey", "timestamp",
                       "lamport_clock", "signature")})

    @classmethod
    def create(cls, belongs_to: str, payer_key: str, debtor_key: str,
               amount: int, author_pubkey: str,
               lamport_clock: int = 0) -> "Split":
        return cls(
            id=str(uuid.uuid4()), belongs_to=belongs_to,
            payer_key=payer_key, debtor_key=debtor_key, amount=amount,
            author_pubkey=author_pubkey, timestamp=int(time.time()),
            lamport_clock=lamport_clock)


def split_equally(expense_id: str, amount: int, payer_key: str,
                  debtor_keys: list[str],
                  lamport_clock: int = 0) -> list[Split]:
    """Integer-exact equal split. Remainder goes to first debtor."""
    n = len(debtor_keys)
    if n == 0:
        return []
    share     = amount // n
    remainder = amount - share * n
    splits = []
    for i, dk in enumerate(debtor_keys):
        splits.append(Split.create(
            belongs_to=expense_id, payer_key=payer_key, debtor_key=dk,
            amount=share + (remainder if i == 0 else 0),
            author_pubkey=payer_key, lamport_clock=lamport_clock))
    return splits


def split_custom(expense_id: str, payer_key: str,
                 amounts: dict[str, int],
                 lamport_clock: int = 0) -> list[Split]:
    """Custom amounts per debtor pubkey."""
    return [Split.create(belongs_to=expense_id, payer_key=payer_key,
                         debtor_key=dk, amount=amt,
                         author_pubkey=payer_key, lamport_clock=lamport_clock)
            for dk, amt in amounts.items()]


# ---------------------------------------------------------------------------
# Expense (maps to expenses table)
# ---------------------------------------------------------------------------

@dataclass
class Expense:
    id:                str
    group_id:          str
    timestamp:         int
    expense_date:      int   # epoch seconds of the actual expense date
    lamport_clock:     int
    author_pubkey:     str
    is_deleted:        int   # 0=active, 1=deleted (tombstone)
    amount:            int   # smallest currency unit
    description:       str
    category:          Optional[str]  = None
    original_amount:   Optional[int]  = None  # only for foreign-currency expenses
    original_currency: Optional[str]  = None
    signature:         str            = ""
    splits:            list[Split]    = field(default_factory=list)

    def canonical_bytes(self) -> bytes:
        """Deterministic bytes for Ed25519 signing. No local-only fields."""
        return (f"{self.id}|{self.group_id}|{self.amount}"
                f"|{self.description or ''}|{self.category or ''}"
                f"|{self.expense_date}|{self.original_amount or 0}"
                f"|{self.original_currency or ''}|{self.author_pubkey}"
                f"|{self.timestamp}|{self.lamport_clock}"
                f"|{self.is_deleted}").encode()

    def to_wire_dict(self) -> dict:
        """Serialization for network transmission. No local-only fields."""
        return {
            "id":                self.id,
            "group_id":          self.group_id,
            "timestamp":         self.timestamp,
            "expense_date":      self.expense_date,
            "lamport_clock":     self.lamport_clock,
            "author_pubkey":     self.author_pubkey,
            "is_deleted":        self.is_deleted,
            "amount":            self.amount,
            "description":       self.description,
            "category":          self.category,
            "original_amount":   self.original_amount,
            "original_currency": self.original_currency,
            "signature":         self.signature,
            "splits":            [s.to_wire_dict() for s in self.splits],
        }

    @classmethod
    def from_wire_dict(cls, d: dict) -> "Expense":
        splits = [Split.from_wire_dict(s) for s in d.get("splits", [])]
        return cls(
            id=d["id"], group_id=d["group_id"],
            timestamp=d["timestamp"], expense_date=d["expense_date"],
            lamport_clock=d["lamport_clock"], author_pubkey=d["author_pubkey"],
            is_deleted=d.get("is_deleted", 0), amount=d["amount"],
            description=d.get("description", ""),
            category=d.get("category"),
            original_amount=d.get("original_amount"),
            original_currency=d.get("original_currency"),
            signature=d.get("signature", ""),
            splits=splits)

    @classmethod
    def create(cls, group_id: str, description: str, amount: int,
               author_pubkey: str, expense_date: int = None,
               category: str = None, original_amount: int = None,
               original_currency: str = None,
               lamport_clock: int = 0) -> "Expense":
        now = int(time.time())
        return cls(
            id=str(uuid.uuid4()), group_id=group_id,
            timestamp=now, expense_date=expense_date or now,
            lamport_clock=lamport_clock, author_pubkey=author_pubkey,
            is_deleted=0, amount=amount, description=description,
            category=category, original_amount=original_amount,
            original_currency=original_currency)


# ---------------------------------------------------------------------------
# Settlement (maps to settlements table)
# ---------------------------------------------------------------------------

@dataclass
class Settlement:
    id:            str
    group_id:      str
    timestamp:     int
    lamport_clock: int
    author_pubkey: str
    is_deleted:    int   # 0=active, 1=deleted
    from_key:      str   # who pays
    to_key:        str   # who receives
    amount:        int   # smallest currency unit
    signature:     str = ""

    def canonical_bytes(self) -> bytes:
        return (f"{self.id}|{self.group_id}|{self.from_key}"
                f"|{self.to_key}|{self.amount}|{self.author_pubkey}"
                f"|{self.timestamp}|{self.lamport_clock}"
                f"|{self.is_deleted}").encode()

    def to_wire_dict(self) -> dict:
        return {
            "id":            self.id,
            "group_id":      self.group_id,
            "timestamp":     self.timestamp,
            "lamport_clock": self.lamport_clock,
            "author_pubkey": self.author_pubkey,
            "is_deleted":    self.is_deleted,
            "from_key":      self.from_key,
            "to_key":        self.to_key,
            "amount":        self.amount,
            "signature":     self.signature,
        }

    @classmethod
    def from_wire_dict(cls, d: dict) -> "Settlement":
        return cls(**{k: d[k] for k in
                      ("id", "group_id", "timestamp", "lamport_clock",
                       "author_pubkey", "is_deleted", "from_key",
                       "to_key", "amount", "signature")})

    @classmethod
    def create(cls, group_id: str, from_key: str, to_key: str,
               amount: int, author_pubkey: str,
               lamport_clock: int = 0) -> "Settlement":
        return cls(
            id=str(uuid.uuid4()), group_id=group_id,
            timestamp=int(time.time()), lamport_clock=lamport_clock,
            author_pubkey=author_pubkey, is_deleted=0,
            from_key=from_key, to_key=to_key, amount=amount)


# ---------------------------------------------------------------------------
# UserComment (maps to comments_user table)
# ---------------------------------------------------------------------------

@dataclass
class UserComment:
    id:            str
    belongs_to:    str
    timestamp:     int
    lamport_clock: int
    author_pubkey: str
    is_deleted:    int
    comment:       str
    signature:     str = ""

    def canonical_bytes(self) -> bytes:
        return (f"{self.id}|{self.belongs_to}|{self.comment or ''}"
                f"|{self.author_pubkey}|{self.timestamp}"
                f"|{self.lamport_clock}|{self.is_deleted}").encode()

    def to_wire_dict(self) -> dict:
        return {
            "id":            self.id,
            "belongs_to":    self.belongs_to,
            "timestamp":     self.timestamp,
            "lamport_clock": self.lamport_clock,
            "author_pubkey": self.author_pubkey,
            "is_deleted":    self.is_deleted,
            "comment":       self.comment,
            "signature":     self.signature,
        }

    @classmethod
    def from_wire_dict(cls, d: dict) -> "UserComment":
        return cls(**{k: d[k] for k in
                      ("id", "belongs_to", "timestamp", "lamport_clock",
                       "author_pubkey", "is_deleted", "comment",
                       "signature")})

    @classmethod
    def create(cls, belongs_to: str, comment: str, author_pubkey: str,
               lamport_clock: int = 0) -> "UserComment":
        return cls(
            id=str(uuid.uuid4()), belongs_to=belongs_to,
            timestamp=int(time.time()), lamport_clock=lamport_clock,
            author_pubkey=author_pubkey, is_deleted=0, comment=comment)


# ---------------------------------------------------------------------------
# Attachment (maps to attachments table)
# ---------------------------------------------------------------------------

# is_stored values — local-only, never synced
ATTACHMENT_NOT_STORED    = 0  # not yet downloaded
ATTACHMENT_STORED        = 1  # file present on disk
ATTACHMENT_DELETED_LOCAL = 2  # intentionally removed locally, record kept

@dataclass
class Attachment:
    id:            str
    belongs_to:    str
    timestamp:     int
    lamport_clock: int
    author_pubkey: str
    sha256:        str
    filename:      str
    mime:          Optional[str]
    size:          Optional[int]
    signature:     str = ""
    # LOCAL ONLY — excluded from canonical_bytes and to_wire_dict
    is_stored:     int = ATTACHMENT_NOT_STORED

    def canonical_bytes(self) -> bytes:
        """is_stored is intentionally excluded."""
        return (f"{self.id}|{self.belongs_to}|{self.sha256}"
                f"|{self.filename}|{self.mime or ''}|{self.size or 0}"
                f"|{self.author_pubkey}|{self.timestamp}"
                f"|{self.lamport_clock}").encode()

    def to_wire_dict(self) -> dict:
        """is_stored is intentionally excluded."""
        return {
            "id":            self.id,
            "belongs_to":    self.belongs_to,
            "timestamp":     self.timestamp,
            "lamport_clock": self.lamport_clock,
            "author_pubkey": self.author_pubkey,
            "sha256":        self.sha256,
            "filename":      self.filename,
            "mime":          self.mime,
            "size":          self.size,
            "signature":     self.signature,
        }

    @classmethod
    def from_wire_dict(cls, d: dict) -> "Attachment":
        return cls(
            id=d["id"], belongs_to=d["belongs_to"],
            timestamp=d["timestamp"], lamport_clock=d["lamport_clock"],
            author_pubkey=d["author_pubkey"], sha256=d["sha256"],
            filename=d["filename"], mime=d.get("mime"),
            size=d.get("size"), signature=d.get("signature", ""),
            is_stored=ATTACHMENT_NOT_STORED)  # always reset on receive

    @classmethod
    def create(cls, belongs_to: str, sha256: str, filename: str,
               author_pubkey: str, mime: str = None, size: int = None,
               lamport_clock: int = 0) -> "Attachment":
        return cls(
            id=str(uuid.uuid4()), belongs_to=belongs_to,
            timestamp=int(time.time()), lamport_clock=lamport_clock,
            author_pubkey=author_pubkey, sha256=sha256, filename=filename,
            mime=mime, size=size, is_stored=ATTACHMENT_STORED)

    def size_str(self) -> str:
        if not self.size:
            return "?"
        if self.size < 1024:
            return f"{self.size} B"
        if self.size < 1024 ** 2:
            return f"{self.size / 1024:.1f} KB"
        return f"{self.size / 1024**2:.1f} MB"

    @property
    def available(self) -> bool:
        return self.is_stored == ATTACHMENT_STORED

    @property
    def locally_deleted(self) -> bool:
        return self.is_stored == ATTACHMENT_DELETED_LOCAL
