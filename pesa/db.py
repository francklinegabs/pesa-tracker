"""SQLite-backed ledger: transactions, accounts, budgets, recurring items and savings goals."""

from __future__ import annotations

import calendar
import dataclasses
import json
import os
import sqlite3
from datetime import date
from pathlib import Path

from .models import Transaction

DEFAULT_PATH = Path(os.environ.get("PESA_DB", Path.home() / ".pesa" / "pesa.db"))
DEFAULT_ACCOUNT = "mpesa"
ACCOUNT_KINDS = ("mobile", "bank", "cash", "savings")
SCHEMA_VERSION = 1

SCHEMA_V1 = """
CREATE TABLE accounts (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL DEFAULT 'cash',
    opening_balance REAL NOT NULL DEFAULT 0
);
CREATE TABLE recurring (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    amount      REAL NOT NULL CHECK (amount > 0),
    category    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    day         INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
    next_on     TEXT NOT NULL
);
CREATE TABLE transactions (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('expense', 'income', 'transfer')),
    amount        REAL NOT NULL CHECK (amount > 0),
    category      TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    occurred_on   TEXT NOT NULL,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    to_account_id INTEGER REFERENCES accounts(id),
    ref           TEXT UNIQUE,
    recurring_id  INTEGER REFERENCES recurring(id) ON DELETE SET NULL
);
CREATE INDEX idx_transactions_date ON transactions(occurred_on);
CREATE TABLE budgets (
    category      TEXT PRIMARY KEY,
    monthly_limit REAL NOT NULL CHECK (monthly_limit > 0)
);
CREATE TABLE goals (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    target   REAL NOT NULL CHECK (target > 0),
    saved    REAL NOT NULL DEFAULT 0,
    deadline TEXT
);
"""

_TX_SELECT = """
SELECT t.*, a.name AS account, b.name AS to_account
FROM transactions t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN accounts b ON b.id = t.to_account_id
"""


def add_months(d: date, months: int, day: int | None = None) -> date:
    """Move `d` by whole months, clamping the day to the end of shorter months."""
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    return date(year, month, min(day or d.day, calendar.monthrange(year, month)[1]))


def month_prefix(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-%"


class Ledger:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.migrated_from_json = 0
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- schema -----------------------------------------------------------

    def _migrate(self) -> None:
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = self.conn.execute("SELECT version FROM schema_version").fetchone()
        version = row[0] if row else 0
        if version >= SCHEMA_VERSION:
            return
        self.conn.executescript(SCHEMA_V1)
        with self.conn:
            self.conn.execute(
                "INSERT INTO accounts (name, kind) VALUES (?, 'mobile')", (DEFAULT_ACCOUNT,)
            )
            self.conn.execute("DELETE FROM schema_version")
            self.conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
        self._import_legacy_json()

    def _import_legacy_json(self) -> None:
        """Bring in data from the old JSON files (v0.1) if they sit next to the database."""
        expenses_file = self.path.with_name("expenses.json")
        budgets_file = self.path.with_name("expenses.budgets.json")
        if expenses_file.exists():
            for item in json.loads(expenses_file.read_text(encoding="utf-8")):
                note, ref = item.get("note", ""), None
                if note.startswith("MPESA ") and ":" in note:
                    head, note = note.split(":", 1)
                    ref, note = head[len("MPESA "):].strip(), note.strip()
                self.add(item["amount"], item["category"], note,
                         date.fromisoformat(item["spent_on"]), ref=ref)
                self.migrated_from_json += 1
        if budgets_file.exists():
            for category, limit in json.loads(budgets_file.read_text(encoding="utf-8")).items():
                self.set_budget(category, limit)

    # -- accounts ---------------------------------------------------------

    def _account_id(self, name: str) -> int:
        row = self.conn.execute(
            "SELECT id FROM accounts WHERE name = ?", (name.strip().lower(),)
        ).fetchone()
        if row is None:
            raise ValueError(f"no account named {name!r}")
        return row["id"]

    def add_account(self, name: str, kind: str = "cash", opening_balance: float = 0.0) -> None:
        name = name.strip().lower()
        if not name:
            raise ValueError("account name cannot be empty")
        if kind not in ACCOUNT_KINDS:
            raise ValueError(f"account kind must be one of {', '.join(ACCOUNT_KINDS)}")
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO accounts (name, kind, opening_balance) VALUES (?, ?, ?)",
                    (name, kind, float(opening_balance)),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"account {name!r} already exists") from None

    def balances(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT a.name, a.kind,
                   a.opening_balance
                   + COALESCE((SELECT SUM(CASE t.kind WHEN 'income' THEN t.amount ELSE -t.amount END)
                               FROM transactions t WHERE t.account_id = a.id), 0)
                   + COALESCE((SELECT SUM(t.amount) FROM transactions t
                               WHERE t.to_account_id = a.id), 0) AS balance
            FROM accounts a ORDER BY a.name
        """).fetchall()
        return [{"name": r["name"], "kind": r["kind"], "balance": round(r["balance"], 2)} for r in rows]

    # -- transactions -----------------------------------------------------

    def _row_to_tx(self, row: sqlite3.Row) -> Transaction:
        return Transaction(
            id=row["id"], amount=row["amount"], category=row["category"], note=row["note"],
            occurred_on=date.fromisoformat(row["occurred_on"]), kind=row["kind"],
            account=row["account"], to_account=row["to_account"], ref=row["ref"],
        )

    def add(self, amount: float, category: str, note: str = "", occurred_on: date | None = None,
            kind: str = "expense", account: str = DEFAULT_ACCOUNT, to_account: str | None = None,
            ref: str | None = None, recurring_id: int | None = None) -> Transaction:
        tx = Transaction(0, amount, category, note, occurred_on or date.today(),
                         kind, account, to_account, ref)
        try:
            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO transactions (kind, amount, category, note, occurred_on,
                                                 account_id, to_account_id, ref, recurring_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tx.kind, tx.amount, tx.category, tx.note, tx.occurred_on.isoformat(),
                     self._account_id(tx.account),
                     self._account_id(tx.to_account) if tx.to_account else None,
                     tx.ref, recurring_id),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"a transaction with reference {ref!r} already exists") from None
        tx.id = cur.lastrowid
        return tx

    def transfer(self, amount: float, from_account: str, to_account: str,
                 note: str = "", occurred_on: date | None = None) -> Transaction:
        return self.add(amount, "transfer", note, occurred_on, "transfer", from_account, to_account)

    def has_ref(self, ref: str) -> bool:
        return self.conn.execute("SELECT 1 FROM transactions WHERE ref = ?", (ref,)).fetchone() is not None

    def get(self, tx_id: int) -> Transaction:
        row = self.conn.execute(_TX_SELECT + " WHERE t.id = ?", (tx_id,)).fetchone()
        if row is None:
            raise LookupError(f"no transaction with id {tx_id}")
        return self._row_to_tx(row)

    def delete(self, tx_id: int) -> Transaction:
        tx = self.get(tx_id)
        with self.conn:
            self.conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        return tx

    def update(self, tx_id: int, **changes) -> Transaction:
        """Apply `changes` (field name -> new value) and re-validate the transaction."""
        updated = dataclasses.replace(self.get(tx_id), **changes)
        with self.conn:
            self.conn.execute(
                """UPDATE transactions SET kind = ?, amount = ?, category = ?, note = ?,
                       occurred_on = ?, account_id = ?, to_account_id = ? WHERE id = ?""",
                (updated.kind, updated.amount, updated.category, updated.note,
                 updated.occurred_on.isoformat(), self._account_id(updated.account),
                 self._account_id(updated.to_account) if updated.to_account else None, tx_id),
            )
        return updated

    def transactions(self, since: date | None = None, until: date | None = None,
                     category: str | None = None, kind: str | None = None,
                     account: str | None = None, search: str | None = None) -> list[Transaction]:
        where, params = [], []
        if since:
            where.append("t.occurred_on >= ?")
            params.append(since.isoformat())
        if until:
            where.append("t.occurred_on <= ?")
            params.append(until.isoformat())
        if category:
            where.append("t.category = ?")
            params.append(category.strip().lower())
        if kind:
            where.append("t.kind = ?")
            params.append(kind)
        if account:
            where.append("(a.name = ? OR b.name = ?)")
            params += [account.strip().lower()] * 2
        if search:
            where.append("(t.note LIKE ? OR t.category LIKE ?)")
            params += [f"%{search.strip()}%"] * 2
        sql = _TX_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        rows = self.conn.execute(sql + " ORDER BY t.occurred_on, t.id", params).fetchall()
        return [self._row_to_tx(r) for r in rows]

    def categories(self) -> list[str]:
        rows = self.conn.execute("""
            SELECT category FROM transactions WHERE kind != 'transfer'
            UNION SELECT category FROM budgets ORDER BY 1
        """).fetchall()
        return [r[0] for r in rows]

    def month_totals(self, year: int, month: int, kind: str = "expense") -> dict[str, float]:
        rows = self.conn.execute(
            """SELECT category, SUM(amount) FROM transactions
               WHERE kind = ? AND occurred_on LIKE ? GROUP BY category""",
            (kind, month_prefix(year, month)),
        ).fetchall()
        return {r[0]: round(r[1], 2) for r in rows}

    # -- budgets ----------------------------------------------------------

    @property
    def budgets(self) -> dict[str, float]:
        rows = self.conn.execute("SELECT category, monthly_limit FROM budgets ORDER BY category")
        return {r[0]: r[1] for r in rows}

    def set_budget(self, category: str, limit: float) -> None:
        if float(limit) <= 0:
            raise ValueError("budget must be positive")
        category = category.strip().lower()
        if not category:
            raise ValueError("category cannot be empty")
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO budgets (category, monthly_limit) VALUES (?, ?)",
                (category, float(limit)),
            )

    def remove_budget(self, category: str) -> None:
        key = category.strip().lower()
        with self.conn:
            if self.conn.execute("DELETE FROM budgets WHERE category = ?", (key,)).rowcount == 0:
                raise ValueError(f"no budget for {key!r}")

    # -- recurring --------------------------------------------------------

    def add_recurring(self, kind: str, amount: float, category: str, day: int,
                      account: str = DEFAULT_ACCOUNT, note: str = "",
                      start_on: date | None = None) -> int:
        if kind not in ("expense", "income"):
            raise ValueError("recurring items are either expense or income")
        if not 1 <= day <= 31:
            raise ValueError("day must be between 1 and 31")
        tx = Transaction(0, amount, category, note, kind=kind, account=account)  # validates
        start = start_on or date.today()
        next_on = add_months(start, 0, day)
        if next_on < start:
            next_on = add_months(start, 1, day)
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO recurring (kind, amount, category, note, account_id, day, next_on)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (kind, tx.amount, tx.category, tx.note, self._account_id(tx.account), day,
                 next_on.isoformat()),
            )
        return cur.lastrowid

    def recurring(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT r.id, r.kind, r.amount, r.category, r.note, r.day, r.next_on, a.name AS account
            FROM recurring r JOIN accounts a ON a.id = r.account_id ORDER BY r.next_on, r.id
        """).fetchall()
        return [dict(r) for r in rows]

    def remove_recurring(self, rec_id: int) -> None:
        with self.conn:
            if self.conn.execute("DELETE FROM recurring WHERE id = ?", (rec_id,)).rowcount == 0:
                raise ValueError(f"no recurring item with id {rec_id}")

    def generate_due(self, today: date | None = None) -> list[Transaction]:
        """Create transactions for every recurring item that has fallen due."""
        today = today or date.today()
        created = []
        for item in self.recurring():
            next_on = date.fromisoformat(item["next_on"])
            while next_on <= today:
                created.append(self.add(item["amount"], item["category"], item["note"], next_on,
                                        item["kind"], item["account"], recurring_id=item["id"]))
                next_on = add_months(next_on, 1, item["day"])
            if next_on.isoformat() != item["next_on"]:
                with self.conn:
                    self.conn.execute("UPDATE recurring SET next_on = ? WHERE id = ?",
                                      (next_on.isoformat(), item["id"]))
        return created

    # -- savings goals ----------------------------------------------------

    def add_goal(self, name: str, target: float, deadline: date | None = None) -> None:
        name = name.strip()
        if not name:
            raise ValueError("goal name cannot be empty")
        if float(target) <= 0:
            raise ValueError("target must be positive")
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO goals (name, target, deadline) VALUES (?, ?, ?)",
                    (name, float(target), deadline.isoformat() if deadline else None),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"goal {name!r} already exists") from None

    def save_to_goal(self, name: str, amount: float) -> dict:
        if float(amount) == 0:
            raise ValueError("amount cannot be zero")
        with self.conn:
            cur = self.conn.execute(
                "UPDATE goals SET saved = MAX(0, saved + ?) WHERE name = ?", (float(amount), name.strip())
            )
        if cur.rowcount == 0:
            raise ValueError(f"no goal named {name!r}")
        return next(g for g in self.goals() if g["name"] == name.strip())

    def remove_goal(self, name: str) -> None:
        with self.conn:
            if self.conn.execute("DELETE FROM goals WHERE name = ?", (name.strip(),)).rowcount == 0:
                raise ValueError(f"no goal named {name!r}")

    def goals(self, today: date | None = None) -> list[dict]:
        today = today or date.today()
        result = []
        for r in self.conn.execute("SELECT * FROM goals ORDER BY id").fetchall():
            goal = dict(r)
            remaining = max(goal["target"] - goal["saved"], 0)
            goal["remaining"] = round(remaining, 2)
            goal["progress"] = round(min(goal["saved"] / goal["target"], 1), 4)
            goal["per_month"] = None
            if goal["deadline"] and remaining:
                deadline = date.fromisoformat(goal["deadline"])
                months_left = max((deadline.year - today.year) * 12 + deadline.month - today.month, 1)
                goal["per_month"] = round(remaining / months_left, 2)
            result.append(goal)
        return result
