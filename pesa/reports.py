"""Reports built on top of the ledger."""

from __future__ import annotations

from datetime import date

from .db import Ledger, add_months


def cash_flow(ledger: Ledger, end: date, months: int = 6) -> list[dict]:
    """Income, spending and net for each of the `months` months ending with `end`'s month."""
    first = date(end.year, end.month, 1)
    rows = []
    for offset in range(months - 1, -1, -1):
        m = add_months(first, -offset)
        income = sum(ledger.month_totals(m.year, m.month, "income").values())
        expense = sum(ledger.month_totals(m.year, m.month, "expense").values())
        rows.append({
            "month": f"{m.year}-{m.month:02d}",
            "income": round(income, 2),
            "expense": round(expense, 2),
            "net": round(income - expense, 2),
        })
    return rows


def top_categories(ledger: Ledger, year: int, month: int, n: int = 5) -> list[tuple[str, float]]:
    totals = ledger.month_totals(year, month, "expense")
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:n]


def month_over_month(ledger: Ledger, year: int, month: int) -> list[dict]:
    """Spending per category this month versus last month, biggest movers first."""
    prev = add_months(date(year, month, 1), -1)
    current = ledger.month_totals(year, month, "expense")
    previous = ledger.month_totals(prev.year, prev.month, "expense")
    rows = []
    for category in set(current) | set(previous):
        cur, old = current.get(category, 0.0), previous.get(category, 0.0)
        rows.append({
            "category": category,
            "previous": old,
            "current": cur,
            "change": round(cur - old, 2),
            "change_pct": round((cur - old) / old * 100, 1) if old else None,
        })
    return sorted(rows, key=lambda r: abs(r["change"]), reverse=True)
