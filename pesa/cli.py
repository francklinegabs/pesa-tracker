"""Command-line interface: python -m pesa <command> ..."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .storage import DEFAULT_PATH, Store


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}, use YYYY-MM-DD")


def fmt_kes(amount: float) -> str:
    return f"KES {amount:,.2f}"


def cmd_add(store: Store, args: argparse.Namespace) -> int:
    expense = store.add(args.amount, args.category, args.note, args.date)
    print(f"Added #{expense.id}: {fmt_kes(expense.amount)} on {expense.category} ({expense.spent_on})")
    return 0


def cmd_list(store: Store, args: argparse.Namespace) -> int:
    rows = [
        e for e in store.expenses
        if (args.since is None or e.spent_on >= args.since)
        and (args.until is None or e.spent_on <= args.until)
        and (args.category is None or e.category == args.category.lower())
    ]
    rows.sort(key=lambda e: (e.spent_on, e.id))
    if not rows:
        print("No expenses found.")
        return 0
    print(f"{'ID':>4}  {'Date':<10}  {'Category':<14}  {'Amount':>14}  Note")
    for e in rows:
        print(f"{e.id:>4}  {e.spent_on}  {e.category:<14}  {fmt_kes(e.amount):>14}  {e.note}")
    print(f"\n{len(rows)} expense(s), total {fmt_kes(sum(e.amount for e in rows))}")
    return 0


def parse_month(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-"))
        date(year, month, 1)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid month {value!r}, use YYYY-MM")
    return year, month


def cmd_summary(store: Store, args: argparse.Namespace) -> int:
    year, month = args.month or (date.today().year, date.today().month)
    totals: dict[str, float] = {}
    for e in store.expenses:
        if (e.spent_on.year, e.spent_on.month) == (year, month):
            totals[e.category] = totals.get(e.category, 0) + e.amount
    if not totals:
        print(f"No expenses in {year}-{month:02d}.")
        return 0
    grand = sum(totals.values())
    print(f"Spending for {year}-{month:02d}\n")
    for category, amount in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
        share = amount / grand * 100
        print(f"  {category:<14} {fmt_kes(amount):>14}  {share:5.1f}%")
    print(f"\n  {'total':<14} {fmt_kes(grand):>14}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pesa", description="Track your spending in KES.")
    parser.add_argument("--file", default=DEFAULT_PATH, help="path to the data file")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="record an expense")
    add.add_argument("amount", type=float)
    add.add_argument("category")
    add.add_argument("-n", "--note", default="")
    add.add_argument("-d", "--date", type=parse_date, default=None, help="YYYY-MM-DD (default: today)")
    add.set_defaults(func=cmd_add)

    ls = sub.add_parser("list", help="show expenses")
    ls.add_argument("--since", type=parse_date, help="from this date (inclusive)")
    ls.add_argument("--until", type=parse_date, help="up to this date (inclusive)")
    ls.add_argument("-c", "--category")
    ls.set_defaults(func=cmd_list)

    summary = sub.add_parser("summary", help="totals per category for a month")
    summary.add_argument("-m", "--month", type=parse_month, help="YYYY-MM (default: this month)")
    summary.set_defaults(func=cmd_summary)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = Store(args.file)
    try:
        return args.func(store, args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
