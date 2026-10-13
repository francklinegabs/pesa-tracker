import tempfile
import unittest
from datetime import date
from pathlib import Path

from pesa.models import Expense
from pesa.storage import Store


class ExpenseTests(unittest.TestCase):
    def test_category_is_normalised(self):
        e = Expense(1, 100, "  Food ")
        self.assertEqual(e.category, "food")

    def test_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError):
            Expense(1, 0, "food")

    def test_rejects_empty_category(self):
        with self.assertRaises(ValueError):
            Expense(1, 50, "   ")

    def test_dict_round_trip(self):
        e = Expense(3, 450.5, "rent", "october", date(2026, 10, 1))
        self.assertEqual(Expense.from_dict(e.to_dict()), e)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "expenses.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_means_empty_store(self):
        self.assertEqual(Store(self.path).expenses, [])

    def test_add_persists_to_disk(self):
        Store(self.path).add(200, "airtime")
        reloaded = Store(self.path)
        self.assertEqual(len(reloaded.expenses), 1)
        self.assertEqual(reloaded.expenses[0].category, "airtime")

    def test_ids_increment(self):
        store = Store(self.path)
        first = store.add(10, "food")
        second = store.add(20, "food")
        self.assertEqual((first.id, second.id), (1, 2))

    def test_custom_date_is_kept(self):
        store = Store(self.path)
        e = store.add(99, "food", spent_on=date(2026, 1, 15))
        self.assertEqual(Store(self.path).expenses[0].spent_on, e.spent_on)


if __name__ == "__main__":
    unittest.main()
