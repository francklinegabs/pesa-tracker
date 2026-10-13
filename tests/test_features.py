import contextlib
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pesa.cli import main
from pesa.mpesa import guess_category, read_statement
from pesa.storage import Store

FIXTURE = Path(__file__).parent / "fixtures" / "mpesa_statement.csv"


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "expenses.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--file", str(self.path), *argv])
        self.assertEqual(code, 0)
        return out.getvalue()


class SummaryTests(TempStoreCase):
    def test_month_totals_only_count_that_month(self):
        store = Store(self.path)
        store.add(100, "food", spent_on=date(2026, 9, 30))
        store.add(200, "food", spent_on=date(2026, 10, 1))
        store.add(50, "transport", spent_on=date(2026, 10, 31))
        self.assertEqual(store.month_totals(2026, 10), {"food": 200, "transport": 50})

    def test_summary_output_lists_categories(self):
        Store(self.path).add(300, "rent", spent_on=date(2026, 10, 2))
        output = self.run_cli("summary", "-m", "2026-10")
        self.assertIn("rent", output)
        self.assertIn("KES 300.00", output)


class BudgetTests(TempStoreCase):
    def test_budget_persists(self):
        Store(self.path).set_budget("Food", 5000)
        self.assertEqual(Store(self.path).budgets, {"food": 5000.0})

    def test_budget_must_be_positive(self):
        with self.assertRaises(ValueError):
            Store(self.path).set_budget("food", 0)

    def test_remove_unknown_budget_fails(self):
        with self.assertRaises(ValueError):
            Store(self.path).remove_budget("rent")

    def test_add_warns_when_over_budget(self):
        Store(self.path).set_budget("food", 1000)
        output = self.run_cli("add", "1500", "food")
        self.assertIn("over budget by KES 500.00", output)

    def test_add_gives_heads_up_near_limit(self):
        Store(self.path).set_budget("food", 1000)
        output = self.run_cli("add", "850", "food")
        self.assertIn("Heads up", output)


class MpesaTests(TempStoreCase):
    def test_reads_only_completed_money_out(self):
        rows = read_statement(FIXTURE)
        self.assertEqual(len(rows), 6)
        self.assertNotIn("SJA1B2C3E0", [r.receipt for r in rows])  # failed
        self.assertNotIn("SJA1B2C3D8", [r.receipt for r in rows])  # money in

    def test_amounts_are_positive(self):
        amounts = [r.amount for r in read_statement(FIXTURE)]
        self.assertEqual(sum(amounts), 4655.0)

    def test_guess_category(self):
        self.assertEqual(guess_category("Pay Bill Charge"), "fees")
        self.assertEqual(guess_category("Merchant Payment to 1 - SHOP"), "shopping")
        self.assertEqual(guess_category("Something unusual"), "other")

    def test_import_is_idempotent(self):
        self.run_cli("import", str(FIXTURE))
        self.run_cli("import", str(FIXTURE))
        self.assertEqual(len(Store(self.path).expenses), 6)

    def test_dry_run_saves_nothing(self):
        self.run_cli("import", str(FIXTURE), "--dry-run")
        self.assertEqual(Store(self.path).expenses, [])

    def test_missing_columns_rejected(self):
        bad = Path(self.tmp.name) / "bad.csv"
        bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_statement(bad)


if __name__ == "__main__":
    unittest.main()
