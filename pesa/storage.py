"""Load and save expenses as a JSON file."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Expense

DEFAULT_PATH = Path(os.environ.get("PESA_FILE", Path.home() / ".pesa" / "expenses.json"))


def _read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


class Store:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.budgets_path = self.path.with_name(self.path.stem + ".budgets.json")
        self.expenses: list[Expense] = []
        self.budgets: dict[str, float] = {}
        self.load()

    def load(self) -> None:
        self.expenses = [Expense.from_dict(item) for item in _read_json(self.path, [])]
        self.budgets = {k: float(v) for k, v in _read_json(self.budgets_path, {}).items()}

    def save(self) -> None:
        _write_json(self.path, [e.to_dict() for e in self.expenses])

    def save_budgets(self) -> None:
        _write_json(self.budgets_path, self.budgets)

    def set_budget(self, category: str, limit: float) -> None:
        if limit <= 0:
            raise ValueError("budget must be positive")
        self.budgets[category.strip().lower()] = float(limit)
        self.save_budgets()

    def remove_budget(self, category: str) -> None:
        key = category.strip().lower()
        if key not in self.budgets:
            raise ValueError(f"no budget for {key!r}")
        del self.budgets[key]
        self.save_budgets()

    def month_totals(self, year: int, month: int) -> dict[str, float]:
        totals: dict[str, float] = {}
        for e in self.expenses:
            if (e.spent_on.year, e.spent_on.month) == (year, month):
                totals[e.category] = totals.get(e.category, 0) + e.amount
        return totals

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
