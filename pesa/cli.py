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
