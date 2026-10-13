"""Import spending from an M-Pesa statement exported as CSV."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

# First keyword found in the "Details" column decides the category.
CATEGORY_RULES = [
    ("airtime", "airtime"),
    ("bundle", "airtime"),
    ("charge", "fees"),
    ("pay bill", "bills"),
    ("paybill", "bills"),
    ("kplc", "bills"),
    ("merchant payment", "shopping"),
    ("buy goods", "shopping"),
    ("withdrawal", "cash"),
    ("withdraw", "cash"),
    ("customer transfer", "transfers"),
    ("send money", "transfers"),
]

COLUMN_ALIASES = {
    "receipt": ["receipt no.", "receipt no", "receipt", "transaction id"],
    "time": ["completion time", "date", "transaction date"],
    "details": ["details", "description"],
    "status": ["transaction status", "status"],
    "withdrawn": ["withdrawn", "paid out", "debit"],
}


@dataclass
class MpesaRow:
    receipt: str
    spent_on: date
    details: str
    amount: float

    @property
    def category(self) -> str:
        return guess_category(self.details)

    @property
    def note(self) -> str:
        return f"MPESA {self.receipt}: {self.details}"


def guess_category(details: str) -> str:
    text = details.lower()
    for keyword, category in CATEGORY_RULES:
        if keyword in text:
            return category
    return "other"


def _parse_amount(value: str) -> float:
    cleaned = value.replace(",", "").replace("KES", "").strip()
    return abs(float(cleaned)) if cleaned else 0.0


def _parse_time(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}")


def _map_columns(header: list[str]) -> dict[str, int]:
    normalised = [h.strip().lower() for h in header]
    mapping = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                mapping[key] = normalised.index(alias)
                break
    missing = {"receipt", "time", "details", "withdrawn"} - mapping.keys()
    if missing:
        raise ValueError(f"statement is missing columns: {', '.join(sorted(missing))}")
    return mapping


def read_statement(path: Path | str) -> list[MpesaRow]:
    """Return the money-out rows of a statement. Failed or incoming rows are skipped."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        cols = _map_columns(next(reader))
        rows = []
        for raw in reader:
            if not raw or not any(cell.strip() for cell in raw):
                continue
            if "status" in cols and raw[cols["status"]].strip().lower() not in ("completed", ""):
                continue
            amount = _parse_amount(raw[cols["withdrawn"]])
            if amount <= 0:
                continue
            rows.append(MpesaRow(
                receipt=raw[cols["receipt"]].strip(),
                spent_on=_parse_time(raw[cols["time"]]),
                details=raw[cols["details"]].strip(),
                amount=amount,
            ))
    return rows
