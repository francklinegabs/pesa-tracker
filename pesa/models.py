"""Data model for a single money transaction."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

KINDS = ("expense", "income", "transfer")


@dataclass
class Transaction:
    id: int
    amount: float  # KES, always positive; `kind` says which way it goes
    category: str
    note: str = ""
    occurred_on: date = field(default_factory=date.today)
    kind: str = "expense"
    account: str = "mpesa"
    to_account: str | None = None  # transfers only
    ref: str | None = None  # external reference, e.g. an M-Pesa receipt number

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        self.amount = round(float(self.amount), 2)
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        self.category = self.category.strip().lower()
        if not self.category:
            raise ValueError("category cannot be empty")
        self.account = self.account.strip().lower()
        if self.to_account is not None:
            self.to_account = self.to_account.strip().lower() or None
        if self.kind == "transfer":
            if not self.to_account:
                raise ValueError("a transfer needs a destination account")
            if self.to_account == self.account:
                raise ValueError("cannot transfer to the same account")
        elif self.to_account is not None:
            raise ValueError("only transfers have a destination account")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["occurred_on"] = self.occurred_on.isoformat()
        return data
