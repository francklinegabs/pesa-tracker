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
