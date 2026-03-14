# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Data Models

Alle Domain-Objekte als Dataclasses.
JSON-serialisierbar für CRDT-Sync und Gruppenverschlüsselung.
"""

from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Member:
    """
    Ein Gruppenmitglied.
    Identität = Ed25519 Public Key (hex).
    """
    pubkey: str
    display_name: str
    joined_at: int = field(default_factory=lambda: int(time.time()))

    def short_key(self) -> str:
        return self.pubkey[:8] + "…"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Member":
        return cls(**d)


@dataclass
class Attachment:
    """
    Dateianhang zu einer Ausgabe.

    Die eigentliche Datei liegt lokal unter storage/<sha256>.
    Im verschlüsselten Expense-Payload stehen nur Metadaten.
    Beim P2P-Sync kann der Empfänger die Datei per Hash anfordern
    und nach dem Download gegen den Hash verifizieren.
    """
    sha256: str       # Hex-Digest — Dateiname im Storage-Ordner
    filename: str     # Original-Dateiname (nur zur Anzeige)
    size: int         # Bytes
    mime_type: str    # z.B. "image/jpeg", "application/pdf"

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


@dataclass
class Split:
    pubkey: str
    amount: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Split":
        return cls(**d)


@dataclass
class Expense:
    """
    Eine Ausgabe.

    CRDT: gleiche id, steigender timestamp → last-write-wins.
    Signatur: Ed25519 über canonical_bytes() mit dem Key des Payers.
    Wird als Ganzes AES-GCM-verschlüsselt mit dem Gruppenkey gespeichert
    und übertragen — andere Gruppen können nichts lesen.
    """
    id: str
    description: str
    amount: float
    currency: str
    payer_pubkey: str
    splits: list[Split]
    timestamp: int
    signature: str
    is_deleted: bool = False
    note: str = ""
    attachment: Optional[Attachment] = None

    @classmethod
    def create(
        cls,
        description: str,
        amount: float,
        currency: str,
        payer_pubkey: str,
        splits: list[Split],
        note: str = "",
        attachment: Optional[Attachment] = None,
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
            note=note,
            attachment=attachment,
        )

    def canonical_bytes(self) -> bytes:
        """Kanonische Bytes für die Signatur (attachment-Hash eingeschlossen)."""
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
        return cls(splits=splits, attachment=attachment, **d)

    def validate_splits(self, tolerance: float = 0.02) -> bool:
        total = sum(s.amount for s in self.splits)
        return abs(total - self.amount) <= tolerance

    def __repr__(self) -> str:
        att = f", attach={self.attachment.filename}" if self.attachment else ""
        return f"Expense('{self.description}', {self.amount} {self.currency}{att})"


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
        splits[0] = Split(pubkey=splits[0].pubkey, amount=round(splits[0].amount + diff, 2))
    return splits


def split_custom(amounts_by_pubkey: dict[str, float]) -> list[Split]:
    return [Split(pubkey=pk, amount=round(amt, 2)) for pk, amt in amounts_by_pubkey.items()]
