"""Command-line interface: python -m pesa <command> ..."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from . import reports
from .db import ACCOUNT_KINDS, DEFAULT_ACCOUNT, DEFAULT_PATH, Ledger
from .models import Transaction
from .mpesa import read_statement
from .sms import parse_messages


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}, use YYYY-MM-DD")


def parse_month(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-"))
        date(year, month, 1)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid month {value!r}, use YYYY-MM")
    return year, month


def this_month() -> tuple[int, int]:
    today = date.today()
    return today.year, today.month


def fmt_kes(amount: float) -> str:
    return f"KES {amount:,.2f}"


def describe(t: Transaction) -> str:
    where = f"{t.account} -> {t.to_account}" if t.kind == "transfer" else t.account
    return f"#{t.id} {t.kind} {fmt_kes(t.amount)} {t.category} [{where}] ({t.occurred_on})"


def print_transactions(rows: list[Transaction]) -> None:
    print(f"{'ID':>4}  {'Date':<10}  {'Type':<8}  {'Account':<16}  {'Category':<12}  {'Amount':>15}  Note")
    for t in rows:
        where = f"{t.account}>{t.to_account}" if t.kind == "transfer" else t.account
        sign = {"income": "+", "expense": "-"}.get(t.kind, " ")
        print(f"{t.id:>4}  {t.occurred_on}  {t.kind:<8}  {where:<16}  {t.category:<12}  "
              f"{sign + fmt_kes(t.amount):>15}  {t.note}")


# -- transactions --------------------------------------------------------------

def warn_if_over_budget(ledger: Ledger, category: str, year: int, month: int) -> None:
    limit = ledger.budgets.get(category)
    if limit is None:
        return
    spent = ledger.month_totals(year, month).get(category, 0)
    if spent > limit:
        print(f"Warning: {category} is over budget by {fmt_kes(spent - limit)} "
              f"({fmt_kes(spent)} of {fmt_kes(limit)})")
    elif spent >= 0.8 * limit:
        print(f"Heads up: {category} has used {spent / limit:.0%} of its {fmt_kes(limit)} budget")


def cmd_add(ledger: Ledger, args: argparse.Namespace) -> int:
    t = ledger.add(args.amount, args.category, args.note, args.date, "expense", args.account)
    print(f"Added {describe(t)}")
    warn_if_over_budget(ledger, t.category, t.occurred_on.year, t.occurred_on.month)
    return 0


def cmd_income(ledger: Ledger, args: argparse.Namespace) -> int:
    t = ledger.add(args.amount, args.category, args.note, args.date, "income", args.account)
    print(f"Added {describe(t)}")
    return 0


def cmd_transfer(ledger: Ledger, args: argparse.Namespace) -> int:
    t = ledger.transfer(args.amount, args.source, args.target, args.note, args.date)
    print(f"Moved {fmt_kes(t.amount)} from {t.account} to {t.to_account} (#{t.id})")
    return 0


def cmd_list(ledger: Ledger, args: argparse.Namespace) -> int:
    rows = ledger.transactions(args.since, args.until, args.category, args.kind,
                               args.account, args.search)
    if not rows:
        print("No transactions found.")
        return 0
    print_transactions(rows)
    income = sum(t.amount for t in rows if t.kind == "income")
    spent = sum(t.amount for t in rows if t.kind == "expense")
    print(f"\n{len(rows)} transaction(s): in {fmt_kes(income)}, out {fmt_kes(spent)}")
    return 0


def cmd_delete(ledger: Ledger, args: argparse.Namespace) -> int:
    print(f"Deleted {describe(ledger.delete(args.id))}")
    return 0


def cmd_edit(ledger: Ledger, args: argparse.Namespace) -> int:
    fields = {"amount": args.amount, "category": args.category, "note": args.note,
              "occurred_on": args.date, "account": args.account}
    t = ledger.update(args.id, **{k: v for k, v in fields.items() if v is not None})
    print(f"Updated {describe(t)} {t.note}")
    return 0


# -- monthly views -------------------------------------------------------------

def cmd_summary(ledger: Ledger, args: argparse.Namespace) -> int:
    year, month = args.month or this_month()
    spending = ledger.month_totals(year, month, "expense")
    income = sum(ledger.month_totals(year, month, "income").values())
    if not spending and not income:
        print(f"No transactions in {year}-{month:02d}.")
        return 0
    total = sum(spending.values())
    print(f"Summary for {year}-{month:02d}\n")
    print(f"  {'income':<14} {fmt_kes(income):>14}")
    print(f"  {'spending':<14} {fmt_kes(total):>14}")
    print(f"  {'net':<14} {fmt_kes(income - total):>14}\n")
    for category, amount in sorted(spending.items(), key=lambda kv: kv[1], reverse=True):
        line = f"  {category:<14} {fmt_kes(amount):>14}  {amount / total * 100:5.1f}%"
        limit = ledger.budgets.get(category)
        if limit is not None:
            flag = "  OVER" if amount > limit else ""
            line += f"   budget {fmt_kes(limit)} ({amount / limit:.0%}){flag}"
        print(line)
    return 0


def cmd_report(ledger: Ledger, args: argparse.Namespace) -> int:
    year, month = args.month or this_month()
    flow = reports.cash_flow(ledger, date(year, month, 1), args.months)
    print(f"Cash flow, last {args.months} months\n")
    print(f"  {'Month':<8} {'Income':>14} {'Spending':>14} {'Net':>14}")
    for row in flow:
        print(f"  {row['month']:<8} {fmt_kes(row['income']):>14} {fmt_kes(row['expense']):>14} "
              f"{fmt_kes(row['net']):>14}")
    top = reports.top_categories(ledger, year, month)
    if top:
        print(f"\nTop spending in {year}-{month:02d}\n")
        for category, amount in top:
            print(f"  {category:<14} {fmt_kes(amount):>14}")
    changes = reports.month_over_month(ledger, year, month)
    if changes:
        print("\nChange vs previous month\n")
        for row in changes:
            pct = f"{row['change_pct']:+.0f}%" if row["change_pct"] is not None else "new"
            print(f"  {row['category']:<14} {fmt_kes(row['previous']):>14} -> "
                  f"{fmt_kes(row['current']):>14}  {pct}")
    return 0


def cmd_budget(ledger: Ledger, args: argparse.Namespace) -> int:
    if args.action == "set":
        ledger.set_budget(args.category, args.limit)
        print(f"Budget for {args.category.lower()} set to {fmt_kes(args.limit)} per month")
        return 0
    if args.action == "remove":
        ledger.remove_budget(args.category)
        print(f"Removed budget for {args.category.lower()}")
        return 0
    budgets = ledger.budgets
    if not budgets:
        print("No budgets set. Try: pesa budget set food 8000")
        return 0
    year, month = this_month()
    totals = ledger.month_totals(year, month)
    print(f"Budgets for {year}-{month:02d}\n")
    for category, limit in budgets.items():
        spent = totals.get(category, 0)
        left = limit - spent
        status = f"left {fmt_kes(left)}" if left >= 0 else f"OVER by {fmt_kes(-left)}"
        print(f"  {category:<14} {fmt_kes(spent):>14} of {fmt_kes(limit):>14}   {status}")
    return 0


# -- accounts, recurring, goals ------------------------------------------------

def cmd_account(ledger: Ledger, args: argparse.Namespace) -> int:
    if args.action == "add":
        ledger.add_account(args.name, args.kind, args.opening)
        print(f"Added {args.kind} account {args.name.lower()} with {fmt_kes(args.opening)}")
        return 0
    rows = ledger.balances()
    for row in rows:
        print(f"  {row['name']:<14} {row['kind']:<8} {fmt_kes(row['balance']):>16}")
    print(f"\n  {'total':<23} {fmt_kes(sum(r['balance'] for r in rows)):>16}")
    return 0


def cmd_recurring(ledger: Ledger, args: argparse.Namespace) -> int:
    if args.action == "add":
        rec_id = ledger.add_recurring(args.kind, args.amount, args.category, args.day,
                                      args.account, args.note, args.start)
        item = next(r for r in ledger.recurring() if r["id"] == rec_id)
        print(f"Recurring #{rec_id}: {args.kind} {fmt_kes(args.amount)} {args.category.lower()} "
              f"on day {args.day} of each month, next on {item['next_on']}")
        return 0
    if args.action == "remove":
        ledger.remove_recurring(args.id)
        print(f"Removed recurring item #{args.id}")
        return 0
    items = ledger.recurring()
    if not items:
        print("No recurring items. Try: pesa recurring add expense 15000 rent --day 1")
        return 0
    for r in items:
        print(f"  #{r['id']:<3} {r['kind']:<8} {fmt_kes(r['amount']):>14}  {r['category']:<12} "
              f"day {r['day']:>2}  next {r['next_on']}  [{r['account']}] {r['note']}")
    return 0


def cmd_goal(ledger: Ledger, args: argparse.Namespace) -> int:
    if args.action == "add":
        ledger.add_goal(args.name, args.target, args.deadline)
        print(f"Goal {args.name!r}: save {fmt_kes(args.target)}"
              + (f" by {args.deadline}" if args.deadline else ""))
        return 0
    if args.action == "save":
        g = ledger.save_to_goal(args.name, args.amount)
        print(f"{g['name']}: {fmt_kes(g['saved'])} of {fmt_kes(g['target'])} ({g['progress']:.0%})")
        return 0
    if args.action == "remove":
        ledger.remove_goal(args.name)
        print(f"Removed goal {args.name!r}")
        return 0
    goals = ledger.goals()
    if not goals:
        print('No goals yet. Try: pesa goal add "laptop" 60000 --deadline 2027-03-01')
        return 0
    for g in goals:
        filled = int(g["progress"] * 20)
        bar = "#" * filled + "-" * (20 - filled)
        line = f"  {g['name']:<16} [{bar}] {g['progress']:>4.0%}  {fmt_kes(g['saved'])} of {fmt_kes(g['target'])}"
        if g["per_month"]:
            line += f"  (save {fmt_kes(g['per_month'])}/month to reach it by {g['deadline']})"
        print(line)
    return 0


# -- import / export -----------------------------------------------------------

CSV_FIELDS = ["id", "date", "kind", "account", "to_account", "category", "amount", "note"]


def cmd_export(ledger: Ledger, args: argparse.Namespace) -> int:
    rows = ledger.transactions()
    if args.month:
        rows = [t for t in rows if (t.occurred_on.year, t.occurred_on.month) == args.month]
    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        writer = csv.writer(out)
        writer.writerow(CSV_FIELDS)
        for t in rows:
            writer.writerow([t.id, t.occurred_on.isoformat(), t.kind, t.account, t.to_account or "",
                             t.category, f"{t.amount:.2f}", t.note])
    finally:
        if out is not sys.stdout:
            out.close()
    if args.output:
        print(f"Exported {len(rows)} transaction(s) to {args.output}")
    return 0


def cmd_import(ledger: Ledger, args: argparse.Namespace) -> int:
    rows = read_statement(args.statement)
    new = [r for r in rows if not ledger.has_ref(r.receipt)]
    for r in new:
        print(f"  {r.spent_on}  {r.category:<10} {fmt_kes(r.amount):>14}  {r.details}")
        if not args.dry_run:
            ledger.add(r.amount, r.category, r.note, r.spent_on, account=args.account, ref=r.receipt)
    skipped = len(rows) - len(new)
    verb = "Would import" if args.dry_run else "Imported"
    print(f"\n{verb} {len(new)} transaction(s), total {fmt_kes(sum(r.amount for r in new))}"
          + (f"; skipped {skipped} already imported" if skipped else ""))
    return 0


def cmd_sms(ledger: Ledger, args: argparse.Namespace) -> int:
    if args.file:
        blob = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        blob = " ".join(args.text)
    else:
        blob = sys.stdin.read()
    parsed, failed = parse_messages(blob)
    added = 0
    for p in parsed:
        if ledger.has_ref(p.ref):
            print(f"  skip {p.ref} (already recorded)")
            continue
        t = ledger.add(p.amount, p.category, p.note, p.occurred_on, p.kind, args.account, ref=p.ref)
        print(f"  added {describe(t)} {t.note}")
        added += 1
        if p.fee > 0:
            ledger.add(p.fee, "fees", f"M-Pesa charge for {p.ref}", p.occurred_on,
                       account=args.account, ref=f"{p.ref}-FEE")
            print(f"  added fee {fmt_kes(p.fee)}")
    for message in failed:
        print(f"  could not read: {message[:60]}...", file=sys.stderr)
    print(f"\nAdded {added} transaction(s) from {len(parsed) + len(failed)} message(s)")
    return 0


def cmd_serve(ledger: Ledger, args: argparse.Namespace) -> int:
    from .web import serve
    ledger.close()
    serve(args.db, args.host, args.port, open_browser=not args.no_browser)
    return 0


# -- parser --------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pesa", description="Track your money in KES.")
    parser.add_argument("--db", default=DEFAULT_PATH, help="path to the database file")
    sub = parser.add_subparsers(dest="command", required=True)

    def money_args(p, default_category=None):
        p.add_argument("amount", type=float)
        if default_category:
            p.add_argument("category", nargs="?", default=default_category)
        else:
            p.add_argument("category")
        p.add_argument("-n", "--note", default="")
        p.add_argument("-d", "--date", type=parse_date, default=None, help="YYYY-MM-DD (default: today)")
        p.add_argument("-a", "--account", default=DEFAULT_ACCOUNT)

    add = sub.add_parser("add", help="record an expense")
    money_args(add)
    add.set_defaults(func=cmd_add)

    income = sub.add_parser("income", help="record money coming in")
    money_args(income, default_category="income")
    income.set_defaults(func=cmd_income)

    transfer = sub.add_parser("transfer", help="move money between your accounts")
    transfer.add_argument("amount", type=float)
    transfer.add_argument("source", help="from account")
    transfer.add_argument("target", help="to account")
    transfer.add_argument("-n", "--note", default="")
    transfer.add_argument("-d", "--date", type=parse_date, default=None)
    transfer.set_defaults(func=cmd_transfer)

    ls = sub.add_parser("list", help="show transactions")
    ls.add_argument("--since", type=parse_date, help="from this date (inclusive)")
    ls.add_argument("--until", type=parse_date, help="up to this date (inclusive)")
    ls.add_argument("-c", "--category")
    ls.add_argument("-k", "--kind", choices=["expense", "income", "transfer"])
    ls.add_argument("-a", "--account")
    ls.add_argument("-s", "--search", help="text to look for in notes and categories")
    ls.set_defaults(func=cmd_list)

    delete = sub.add_parser("delete", help="remove a transaction by id")
    delete.add_argument("id", type=int)
    delete.set_defaults(func=cmd_delete)

    edit = sub.add_parser("edit", help="change fields of a transaction")
    edit.add_argument("id", type=int)
    edit.add_argument("--amount", type=float)
    edit.add_argument("-c", "--category")
    edit.add_argument("-n", "--note")
    edit.add_argument("-d", "--date", type=parse_date)
    edit.add_argument("-a", "--account")
    edit.set_defaults(func=cmd_edit)

    summary = sub.add_parser("summary", help="income, spending and categories for a month")
    summary.add_argument("-m", "--month", type=parse_month, help="YYYY-MM (default: this month)")
    summary.set_defaults(func=cmd_summary)

    report = sub.add_parser("report", help="cash flow, top categories and monthly changes")
    report.add_argument("-m", "--month", type=parse_month, help="YYYY-MM (default: this month)")
    report.add_argument("--months", type=int, default=6, help="months of cash flow to show")
    report.set_defaults(func=cmd_report)

    budget = sub.add_parser("budget", help="monthly budgets per category")
    budget.set_defaults(func=cmd_budget)
    bsub = budget.add_subparsers(dest="action")
    bset = bsub.add_parser("set")
    bset.add_argument("category")
    bset.add_argument("limit", type=float)
    bsub.add_parser("remove").add_argument("category")
    bsub.add_parser("list")

    account = sub.add_parser("account", help="accounts and balances")
    account.set_defaults(func=cmd_account)
    asub = account.add_subparsers(dest="action")
    aadd = asub.add_parser("add")
    aadd.add_argument("name")
    aadd.add_argument("-k", "--kind", choices=ACCOUNT_KINDS, default="cash")
    aadd.add_argument("--opening", type=float, default=0.0, help="starting balance")
    asub.add_parser("list")

    recurring = sub.add_parser("recurring", help="rent, salary and other monthly items")
    recurring.set_defaults(func=cmd_recurring)
    rsub = recurring.add_subparsers(dest="action")
    radd = rsub.add_parser("add")
    radd.add_argument("kind", choices=["expense", "income"])
    radd.add_argument("amount", type=float)
    radd.add_argument("category")
    radd.add_argument("--day", type=int, required=True, help="day of the month (1-31)")
    radd.add_argument("-a", "--account", default=DEFAULT_ACCOUNT)
    radd.add_argument("-n", "--note", default="")
    radd.add_argument("--start", type=parse_date, help="first possible date (default: today)")
    rsub.add_parser("remove").add_argument("id", type=int)
    rsub.add_parser("list")

    goal = sub.add_parser("goal", help="savings goals")
    goal.set_defaults(func=cmd_goal)
    gsub = goal.add_subparsers(dest="action")
    gadd = gsub.add_parser("add")
    gadd.add_argument("name")
    gadd.add_argument("target", type=float)
    gadd.add_argument("--deadline", type=parse_date)
    gsave = gsub.add_parser("save", help="add (or with a negative amount, take out) savings")
    gsave.add_argument("name")
    gsave.add_argument("amount", type=float)
    gsub.add_parser("remove").add_argument("name")
    gsub.add_parser("list")

    export = sub.add_parser("export", help="write transactions as CSV")
    export.add_argument("-o", "--output", help="file to write (default: print to screen)")
    export.add_argument("-m", "--month", type=parse_month, help="only this month, YYYY-MM")
    export.set_defaults(func=cmd_export)

    imp = sub.add_parser("import", help="import spending from an M-Pesa statement CSV")
    imp.add_argument("statement", help="path to the statement CSV")
    imp.add_argument("--dry-run", action="store_true", help="show what would be imported")
    imp.add_argument("-a", "--account", default=DEFAULT_ACCOUNT)
    imp.set_defaults(func=cmd_import)

    sms = sub.add_parser("sms", help="record M-Pesa confirmation messages")
    sms.add_argument("text", nargs="*", help="message text (or use --file, or pipe it in)")
    sms.add_argument("-f", "--file", help="text file with one or more messages")
    sms.add_argument("-a", "--account", default=DEFAULT_ACCOUNT)
    sms.set_defaults(func=cmd_sms)

    serve = sub.add_parser("serve", help="open the web dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ledger = Ledger(args.db)
        if ledger.migrated_from_json:
            print(f"Moved {ledger.migrated_from_json} expense(s) from the old JSON file into {args.db}")
        with ledger:
            if args.command != "serve":
                for t in ledger.generate_due():
                    print(f"Recurring: added {describe(t)}")
            return args.func(ledger, args)
    except (ValueError, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
