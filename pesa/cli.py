"""Command-line interface: python -m pesa <command> ..."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date

from .mpesa import read_statement
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
    warn_if_over_budget(store, expense.category, expense.spent_on.year, expense.spent_on.month)
    return 0


def warn_if_over_budget(store: Store, category: str, year: int, month: int) -> None:
    limit = store.budgets.get(category)
    if limit is None:
        return
    spent = store.month_totals(year, month).get(category, 0)
    if spent > limit:
        print(f"Warning: {category} is over budget by {fmt_kes(spent - limit)} "
              f"({fmt_kes(spent)} of {fmt_kes(limit)})")
    elif spent >= 0.8 * limit:
        print(f"Heads up: {category} has used {spent / limit:.0%} of its {fmt_kes(limit)} budget")


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
    totals = store.month_totals(year, month)
    if not totals:
        print(f"No expenses in {year}-{month:02d}.")
        return 0
    grand = sum(totals.values())
    print(f"Spending for {year}-{month:02d}\n")
    for category, amount in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
        share = amount / grand * 100
        line = f"  {category:<14} {fmt_kes(amount):>14}  {share:5.1f}%"
        limit = store.budgets.get(category)
        if limit is not None:
            flag = "  OVER" if amount > limit else ""
            line += f"   budget {fmt_kes(limit)} ({amount / limit:.0%}){flag}"
        print(line)
    print(f"\n  {'total':<14} {fmt_kes(grand):>14}")
    return 0


def cmd_budget(store: Store, args: argparse.Namespace) -> int:
    if args.action == "set":
        if args.category is None or args.limit is None:
            raise ValueError("usage: pesa budget set <category> <limit>")
        store.set_budget(args.category, args.limit)
        print(f"Budget for {args.category.lower()} set to {fmt_kes(args.limit)} per month")
    elif args.action == "remove":
        if args.category is None:
            raise ValueError("usage: pesa budget remove <category>")
        store.remove_budget(args.category)
        print(f"Removed budget for {args.category.lower()}")
    else:
        if not store.budgets:
            print("No budgets set. Try: pesa budget set food 8000")
            return 0
        today = date.today()
        totals = store.month_totals(today.year, today.month)
        print(f"Budgets for {today.year}-{today.month:02d}\n")
        for category, limit in sorted(store.budgets.items()):
            spent = totals.get(category, 0)
            left = limit - spent
            print(f"  {category:<14} {fmt_kes(spent):>14} of {fmt_kes(limit):>14}   "
                  f"{'left ' + fmt_kes(left) if left >= 0 else 'OVER by ' + fmt_kes(-left)}")
    return 0


def cmd_delete(store: Store, args: argparse.Namespace) -> int:
    e = store.delete(args.id)
    print(f"Deleted #{e.id}: {fmt_kes(e.amount)} on {e.category} ({e.spent_on})")
    return 0


def cmd_edit(store: Store, args: argparse.Namespace) -> int:
    e = store.update(
        args.id,
        amount=args.amount,
        category=args.category,
        note=args.note,
        spent_on=args.date,
    )
    print(f"Updated #{e.id}: {fmt_kes(e.amount)} on {e.category} ({e.spent_on}) {e.note}")
    return 0


CSV_FIELDS = ["id", "date", "category", "amount", "note"]


def cmd_export(store: Store, args: argparse.Namespace) -> int:
    rows = sorted(store.expenses, key=lambda e: (e.spent_on, e.id))
    if args.month:
        rows = [e for e in rows if (e.spent_on.year, e.spent_on.month) == args.month]
    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        writer = csv.writer(out)
        writer.writerow(CSV_FIELDS)
        for e in rows:
            writer.writerow([e.id, e.spent_on.isoformat(), e.category, f"{e.amount:.2f}", e.note])
    finally:
        if out is not sys.stdout:
            out.close()
    if args.output:
        print(f"Exported {len(rows)} expense(s) to {args.output}")
    return 0


def cmd_import(store: Store, args: argparse.Namespace) -> int:
    rows = read_statement(args.statement)
    seen = {e.note.split(":")[0] for e in store.expenses if e.note.startswith("MPESA ")}
    new = [r for r in rows if f"MPESA {r.receipt}" not in seen]
    skipped = len(rows) - len(new)
    for r in new:
        print(f"  {r.spent_on}  {r.category:<10} {fmt_kes(r.amount):>14}  {r.details}")
        if not args.dry_run:
            store.add(r.amount, r.category, r.note, r.spent_on)
    verb = "Would import" if args.dry_run else "Imported"
    print(f"\n{verb} {len(new)} transaction(s), total {fmt_kes(sum(r.amount for r in new))}"
          + (f"; skipped {skipped} already imported" if skipped else ""))
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

    delete = sub.add_parser("delete", help="remove an expense by id")
    delete.add_argument("id", type=int)
    delete.set_defaults(func=cmd_delete)

    edit = sub.add_parser("edit", help="change fields of an expense")
    edit.add_argument("id", type=int)
    edit.add_argument("-a", "--amount", type=float)
    edit.add_argument("-c", "--category")
    edit.add_argument("-n", "--note")
    edit.add_argument("-d", "--date", type=parse_date)
    edit.set_defaults(func=cmd_edit)

    budget = sub.add_parser("budget", help="monthly budgets per category")
    budget.add_argument("action", choices=["list", "set", "remove"], nargs="?", default="list")
    budget.add_argument("category", nargs="?")
    budget.add_argument("limit", type=float, nargs="?")
    budget.set_defaults(func=cmd_budget)

    export = sub.add_parser("export", help="write expenses as CSV")
    export.add_argument("-o", "--output", help="file to write (default: print to screen)")
    export.add_argument("-m", "--month", type=parse_month, help="only this month, YYYY-MM")
    export.set_defaults(func=cmd_export)

    imp = sub.add_parser("import", help="import spending from an M-Pesa statement CSV")
    imp.add_argument("statement", help="path to the statement CSV")
    imp.add_argument("--dry-run", action="store_true", help="show what would be imported")
    imp.set_defaults(func=cmd_import)

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
