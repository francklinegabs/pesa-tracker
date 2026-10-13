"""Data model for a single expense."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Expense:
    id: int
    amount: float  # KES
    category: str
    note: str = ""
    spent_on: date = field(default_factory=date.today)

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        self.category = self.category.strip().lower()
        if not self.category:
            raise ValueError("category cannot be empty")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["spent_on"] = self.spent_on.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Expense":
        return cls(
            id=int(data["id"]),
            amount=float(data["amount"]),
            category=data["category"],
            note=data.get("note", ""),
            spent_on=date.fromisoformat(data["spent_on"]),
        )
