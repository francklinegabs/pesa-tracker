"""Load and save expenses as a JSON file."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Expense

DEFAULT_PATH = Path(os.environ.get("PESA_FILE", Path.home() / ".pesa" / "expenses.json"))


class Store:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.expenses: list[Expense] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.expenses = []
            return
        with self.path.open(encoding="utf-8") as f:
            raw = json.load(f)
        self.expenses = [Expense.from_dict(item) for item in raw]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.expenses], f, indent=2)
        tmp.replace(self.path)

    def next_id(self) -> int:
        return max((e.id for e in self.expenses), default=0) + 1

    def add(self, amount: float, category: str, note: str = "", spent_on=None) -> Expense:
        kwargs = {"spent_on": spent_on} if spent_on else {}
        expense = Expense(self.next_id(), amount, category, note, **kwargs)
        self.expenses.append(expense)
        self.save()
        return expense

    def get(self, expense_id: int) -> Expense:
        for e in self.expenses:
            if e.id == expense_id:
                return e
        raise ValueError(f"no expense with id {expense_id}")

    def delete(self, expense_id: int) -> Expense:
        expense = self.get(expense_id)
        self.expenses.remove(expense)
        self.save()
        return expense

    def update(self, expense_id: int, **changes) -> Expense:
        current = self.get(expense_id)
        data = current.to_dict()
        for key, value in changes.items():
            if value is not None:
                data[key] = value.isoformat() if key == "spent_on" else value
        updated = Expense.from_dict(data)  # re-validates
        self.expenses[self.expenses.index(current)] = updated
        self.save()
        return updated
