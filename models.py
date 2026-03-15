# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Data Models

Alle Domain-Objekte als Dataclasses, JSON-serialisierbar.
"""

from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

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
    amount: float

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
    Eine Ausgabe.

    CRDT-Merge-Prioritaet (Lamport + Tiebreaker):
      1. lamport_clock  - kausalitaetsbasiert, uhrzeit-unabhaengig
      2. timestamp      - Wanduhr-Tiebreaker bei gleichem Lamport-Wert
      3. payer_pubkey   - deterministischer letzter Tiebreaker (lexikografisch)
    timestamp   : Wanduhr - nur fuer Anzeige + Tiebreaker
    expense_date: Anzeige-Datum (vom Nutzer gewaehlt) - Unix-Tagesbeginn UTC
                  0 = nicht gesetzt -> timestamp wird angezeigt
    """
    id: str
    description: str
    amount: float
    currency: str
    payer_pubkey: str
    splits: list[Split]
    timestamp: int
    signature: str
    lamport_clock: int = 0     # Lamport-Uhr - primaere CRDT-Ordnung
    category: str = "Allgemein"
    expense_date: int = 0          # User-chosen display date (UTC day start)
    is_deleted: bool = False
    note: str = ""
    attachment: Optional[Attachment] = None
    original_amount: Optional[float] = None
    original_currency: Optional[str] = None

    def display_date(self) -> int:
        """Datum fuer die Anzeige: expense_date falls gesetzt, sonst timestamp."""
        return self.expense_date if self.expense_date else self.timestamp

    @classmethod
    def create(
        cls,
        description: str,
        amount: float,
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
            amount=round(amount, 2),
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
    Erfasst, dass `from_pubkey` an `to_pubkey` einen Betrag gezahlt hat.

    Unterschied zur berechneten Settlement (ledger.py):
      - Diese Klasse ist persistiert + signiert + CRDT-synchronisiert.
      - Die berechnete Settlement ist nur eine Empfehlung.

    CRDT: gleiche id, steigender timestamp -> last-write-wins.
    """
    id: str
    from_pubkey: str    # wer hat gezahlt
    to_pubkey: str      # an wen
    amount: float
    currency: str
    timestamp: int      # CRDT-Uhr
    signature: str      # Ed25519 ueber canonical_bytes(), signiert von from_pubkey
    lamport_clock: int = 0     # Lamport-Uhr - primaere CRDT-Ordnung
    settlement_date: int = 0   # Anzeige-Datum (UTC-Tagesbeginn), 0 = timestamp
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
            amount=round(amount, 2),
            currency=currency,
            timestamp=int(time.time()),
            signature="",
            lamport_clock=0,  # wird in gui.py gesetzt
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

def split_equally(amount: float, pubkeys: list[str]) -> list[Split]:
    n = len(pubkeys)
    if n == 0:
        return []
    share = round(amount / n, 2)
    splits = [Split(pubkey=pk, amount=share) for pk in pubkeys]
    diff = round(amount - sum(s.amount for s in splits), 2)
    if diff:
        splits[0] = Split(splits[0].pubkey, round(splits[0].amount + diff, 2))
    return splits


def split_custom(amounts_by_pubkey: dict[str, float]) -> list[Split]:
    return [Split(pubkey=pk, amount=round(amt, 2)) for pk, amt in amounts_by_pubkey.items()]


def split_by_percent(amount: float,
                     percentages_by_pubkey: dict[str, float]) -> list[Split]:
    """
    Teilt einen Betrag nach Prozentwerten auf.

    Args:
        amount: Gesamtbetrag
        percentages_by_pubkey: {pubkey: prozent}  - Summe sollte 100 ergeben.
            Falls die Summe abweicht, wird proportional skaliert.

    Returns:
        Liste von Splits in absoluten Betraegen.
        Rundungsdifferenz wird auf den ersten Eintrag aufgeschlagen.
    """
    if not percentages_by_pubkey:
        return []
    total_pct = sum(percentages_by_pubkey.values())
    if total_pct <= 0:
        return []
    # Normalisieren falls Summe != 100
    scale = 100.0 / total_pct
    splits = [
        Split(pubkey=pk, amount=round(amount * (pct * scale) / 100.0, 2))
        for pk, pct in percentages_by_pubkey.items()
    ]
    # Rundungsfehler ausgleichen
    diff = round(amount - sum(s.amount for s in splits), 2)
    if diff:
        splits[0] = Split(splits[0].pubkey, round(splits[0].amount + diff, 2))
    return splits
