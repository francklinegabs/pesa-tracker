import json
import unittest
from datetime import date

from pesa.db import Ledger, add_months
from pesa.models import Transaction

from .helpers import LedgerCase


class TransactionModelTests(unittest.TestCase):
    def test_category_and_account_are_normalised(self):
        t = Transaction(1, 100, "  Food ", account=" MPESA ")
        self.assertEqual((t.category, t.account), ("food", "mpesa"))

    def test_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError):
            Transaction(1, 0, "food")

    def test_rejects_empty_category(self):
        with self.assertRaises(ValueError):
            Transaction(1, 50, "   ")

    def test_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            Transaction(1, 50, "food", kind="refund")

    def test_transfer_needs_a_different_destination(self):
        with self.assertRaises(ValueError):
            Transaction(1, 50, "transfer", kind="transfer")
        with self.assertRaises(ValueError):
            Transaction(1, 50, "transfer", kind="transfer", account="bank", to_account="bank")

    def test_only_transfers_have_destination(self):
        with self.assertRaises(ValueError):
            Transaction(1, 50, "food", to_account="bank")


class AddMonthsTests(unittest.TestCase):
    def test_clamps_to_month_end(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_keeps_requested_day_when_possible(self):
        self.assertEqual(add_months(date(2026, 2, 28), 1, day=31), date(2026, 3, 31))

    def test_goes_backwards_across_years(self):
        self.assertEqual(add_months(date(2026, 1, 15), -2), date(2025, 11, 15))


class TransactionTests(LedgerCase):
    def test_add_and_reload(self):
        self.ledger.add(200, "airtime")
        self.ledger.close()
        self.ledger = Ledger(self.path)
        [t] = self.ledger.transactions()
        self.assertEqual((t.id, t.category, t.kind, t.account), (1, "airtime", "expense", "mpesa"))

    def test_unknown_account_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.add(100, "food", account="nowhere")

    def test_duplicate_ref_rejected(self):
        self.ledger.add(100, "food", ref="ABC123")
        with self.assertRaises(ValueError):
            self.ledger.add(100, "food", ref="ABC123")

    def test_update_revalidates(self):
        t = self.ledger.add(100, "food")
        self.assertEqual(self.ledger.update(t.id, amount=150).amount, 150)
        with self.assertRaises(ValueError):
            self.ledger.update(t.id, amount=-1)
        self.assertEqual(self.ledger.get(t.id).amount, 150)

    def test_delete_missing_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self.ledger.delete(42)

    def test_filters(self):
        self.ledger.add_account("bank", "bank")
        self.ledger.add(100, "food", "lunch at work", date(2026, 10, 1))
        self.ledger.add(5000, "salary", "", date(2026, 10, 2), kind="income", account="bank")
        self.ledger.add(300, "transport", "matatu", date(2026, 10, 3))
        ids = lambda rows: [t.id for t in rows]
        self.assertEqual(ids(self.ledger.transactions(kind="income")), [2])
        self.assertEqual(ids(self.ledger.transactions(account="bank")), [2])
        self.assertEqual(ids(self.ledger.transactions(search="lunch")), [1])
        self.assertEqual(ids(self.ledger.transactions(since=date(2026, 10, 2))), [2, 3])
        self.assertEqual(ids(self.ledger.transactions(category="Transport")), [3])

    def test_month_totals_by_kind(self):
        self.ledger.add(100, "food", occurred_on=date(2026, 9, 30))
        self.ledger.add(200, "food", occurred_on=date(2026, 10, 1))
        self.ledger.add(900, "salary", occurred_on=date(2026, 10, 5), kind="income")
        self.assertEqual(self.ledger.month_totals(2026, 10), {"food": 200})
        self.assertEqual(self.ledger.month_totals(2026, 10, "income"), {"salary": 900})


class AccountTests(LedgerCase):
    def test_default_account_exists(self):
        self.assertEqual([a["name"] for a in self.ledger.balances()], ["mpesa"])

    def test_balances_include_income_expense_and_transfers(self):
        self.ledger.add_account("bank", "bank", opening_balance=10000)
        self.ledger.add(3000, "salary", kind="income")          # mpesa +3000
        self.ledger.add(500, "food")                             # mpesa -500
        self.ledger.transfer(2000, "bank", "mpesa")              # bank -2000, mpesa +2000
        balances = {a["name"]: a["balance"] for a in self.ledger.balances()}
        self.assertEqual(balances, {"bank": 8000, "mpesa": 4500})

    def test_duplicate_account_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.add_account("MPESA")

    def test_bad_account_kind_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.add_account("sacco", kind="crypto")

    def test_transfers_do_not_count_as_spending(self):
        self.ledger.add_account("cash")
        self.ledger.transfer(1000, "mpesa", "cash", occurred_on=date(2026, 10, 1))
        self.assertEqual(self.ledger.month_totals(2026, 10), {})


class BudgetTests(LedgerCase):
    def test_budget_set_replace_remove(self):
        self.ledger.set_budget("Food", 5000)
        self.ledger.set_budget("food", 6000)
        self.assertEqual(self.ledger.budgets, {"food": 6000.0})
        self.ledger.remove_budget("food")
        self.assertEqual(self.ledger.budgets, {})

    def test_budget_must_be_positive(self):
        with self.assertRaises(ValueError):
            self.ledger.set_budget("food", 0)

    def test_remove_unknown_budget_fails(self):
        with self.assertRaises(ValueError):
            self.ledger.remove_budget("rent")


class RecurringTests(LedgerCase):
    def test_next_date_is_this_month_if_not_passed(self):
        rec_id = self.ledger.add_recurring("expense", 15000, "rent", 20, start_on=date(2026, 10, 13))
        self.assertEqual(self.ledger.recurring()[0]["next_on"], "2026-10-20")
        self.assertEqual(rec_id, 1)

    def test_next_date_moves_to_next_month_if_passed(self):
        self.ledger.add_recurring("expense", 15000, "rent", 1, start_on=date(2026, 10, 13))
        self.assertEqual(self.ledger.recurring()[0]["next_on"], "2026-11-01")

    def test_generate_due_catches_up_missed_months(self):
        self.ledger.add_recurring("income", 40000, "salary", 28, start_on=date(2026, 8, 1))
        created = self.ledger.generate_due(date(2026, 10, 30))
        self.assertEqual([t.occurred_on for t in created],
                         [date(2026, 8, 28), date(2026, 9, 28), date(2026, 10, 28)])
        self.assertEqual(self.ledger.generate_due(date(2026, 10, 30)), [])
        self.assertEqual(self.ledger.recurring()[0]["next_on"], "2026-11-28")

    def test_day_31_follows_short_months(self):
        self.ledger.add_recurring("expense", 999, "internet", 31, start_on=date(2026, 1, 1))
        created = self.ledger.generate_due(date(2026, 3, 31))
        self.assertEqual([t.occurred_on.day for t in created], [31, 28, 31])

    def test_bad_recurring_items_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.add_recurring("transfer", 100, "x", 1)
        with self.assertRaises(ValueError):
            self.ledger.add_recurring("expense", 100, "rent", 0)
        with self.assertRaises(ValueError):
            self.ledger.remove_recurring(99)


class GoalTests(LedgerCase):
    def test_progress_and_monthly_amount(self):
        self.ledger.add_goal("laptop", 60000, date(2027, 4, 1))
        g = self.ledger.save_to_goal("laptop", 15000)
        self.assertEqual(g["progress"], 0.25)
        [g] = self.ledger.goals(today=date(2026, 10, 13))
        self.assertEqual(g["per_month"], 7500)  # 45,000 over 6 months

    def test_savings_never_go_negative(self):
        self.ledger.add_goal("phone", 20000)
        self.ledger.save_to_goal("phone", -500)
        self.assertEqual(self.ledger.goals()[0]["saved"], 0)

    def test_unknown_or_duplicate_goal(self):
        self.ledger.add_goal("trip", 10000)
        with self.assertRaises(ValueError):
            self.ledger.add_goal("trip", 5000)
        with self.assertRaises(ValueError):
            self.ledger.save_to_goal("car", 100)


class MigrationTests(LedgerCase):
    def test_imports_old_json_files_once(self):
        self.ledger.close()
        self.path.unlink()
        old = [
            {"id": 1, "amount": 250, "category": "food", "note": "lunch", "spent_on": "2026-10-01"},
            {"id": 2, "amount": 100, "category": "airtime",
             "note": "MPESA SJA1B2C3D4: Airtime Purchase", "spent_on": "2026-10-02"},
        ]
        self.path.with_name("expenses.json").write_text(json.dumps(old), encoding="utf-8")
        self.path.with_name("expenses.budgets.json").write_text('{"food": 3000}', encoding="utf-8")

        self.ledger = Ledger(self.path)
        self.assertEqual(self.ledger.migrated_from_json, 2)
        self.assertTrue(self.ledger.has_ref("SJA1B2C3D4"))
        self.assertEqual(self.ledger.budgets, {"food": 3000.0})
        self.ledger.close()

        self.ledger = Ledger(self.path)
        self.assertEqual(self.ledger.migrated_from_json, 0)
        self.assertEqual(len(self.ledger.transactions()), 2)


if __name__ == "__main__":
    unittest.main()
