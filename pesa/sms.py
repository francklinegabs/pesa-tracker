"""Turn M-Pesa confirmation SMS messages into transactions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

REF_RE = re.compile(r"^\s*([A-Z0-9]{10})\s+confirmed", re.IGNORECASE)
AMOUNT_RE = re.compile(r"Ksh\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)
DATE_RE = re.compile(r"on (\d{1,2})/(\d{1,2})/(\d{2,4})", re.IGNORECASE)
FEE_RE = re.compile(r"Transaction cost,?\s*Ksh\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)
PARTY_RE = re.compile(
    r"(?:paid to|sent to|from)\s+(.+?)(?:\s+on\s+\d|\s+for account|\.?\s*New M-PESA|\.\s|$)",
    re.IGNORECASE,
)


@dataclass
class ParsedSms:
    ref: str
    kind: str  # "expense" or "income"
    amount: float
    category: str
    occurred_on: date
    counterparty: str = ""
    fee: float = 0.0

    @property
    def note(self) -> str:
        return self.counterparty


def _money(text: str) -> float:
    return float(text.replace(",", ""))


def _classify(text: str) -> tuple[str, str]:
    lower = text.lower()
    if "you have received" in lower or "received ksh" in lower:
        return "income", "income"
    if "airtime" in lower:
        return "expense", "airtime"
    if "withdraw" in lower:
        return "expense", "cash"
    if "for account" in lower:
        return "expense", "bills"
    if "paid to" in lower:
        return "expense", "shopping"
    if "sent to" in lower:
        return "expense", "transfers"
    raise ValueError("unrecognised M-Pesa message type")


def parse_sms(text: str) -> ParsedSms:
    text = " ".join(text.split())
    ref_match = REF_RE.search(text)
    amount_match = AMOUNT_RE.search(text)
    date_match = DATE_RE.search(text)
    if not (ref_match and amount_match and date_match):
        raise ValueError("not an M-Pesa confirmation message")
    kind, category = _classify(text)
    day, month, year = (int(g) for g in date_match.groups())
    if year < 100:
        year += 2000
    party = PARTY_RE.search(text)
    fee = FEE_RE.search(text)
    return ParsedSms(
        ref=ref_match.group(1).upper(),
        kind=kind,
        amount=_money(amount_match.group(1)),
        category=category,
        occurred_on=date(year, month, day),
        counterparty=party.group(1).strip(" .") if party else "",
        fee=_money(fee.group(1)) if fee else 0.0,
    )


def split_messages(blob: str) -> list[str]:
    """Split pasted text into individual messages (each starts with a receipt code)."""
    parts = re.split(r"(?=\b[A-Z0-9]{10}\s+confirmed)", blob, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def parse_messages(blob: str) -> tuple[list[ParsedSms], list[str]]:
    """Parse every message in `blob`; return (parsed, messages that could not be read)."""
    parsed, failed = [], []
    for message in split_messages(blob):
        try:
            parsed.append(parse_sms(message))
        except ValueError:
            failed.append(message)
    return parsed, failed
