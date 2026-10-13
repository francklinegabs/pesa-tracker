import unittest
from datetime import date
from pathlib import Path

from pesa import reports
from pesa.mpesa import guess_category, read_statement
from pesa.sms import parse_messages, parse_sms

from .helpers import LedgerCase

FIXTURE = Path(__file__).parent / "fixtures" / "mpesa_statement.csv"

SMS_PAID = ("SJA1B2C3D5 Confirmed. Ksh1,250.00 paid to NAIVAS SUPERMARKET. on 1/10/26 at 12:40 PM."
            "New M-PESA balance is Ksh3,650.00. Transaction cost, Ksh0.00.")
SMS_SENT = ("SJA1B2C3D9 Confirmed. Ksh800.00 sent to JANE DOE 0722111111 on 4/10/26 at 10:05 AM. "
            "New M-PESA balance is Ksh4,345.00. Transaction cost, Ksh13.00.")
SMS_BILL = ("SJA1B2C3D6 Confirmed. Ksh500.00 sent to KPLC PREPAID for account 12345678901 on 2/10/26 "
            "at 9:00 AM New M-PESA balance is Ksh3,150.00. Transaction cost, Ksh5.00.")
SMS_RECEIVED = ("SJA1B2C3D8 Confirmed.You have received Ksh2,000.00 from JOHN DOE 0712345678 on 3/10/26 "
                "at 6:22 PM New M-PESA balance is Ksh5,145.00.")
SMS_WITHDRAW = ("SJA1B2C3E1 Confirmed.on 5/10/26 at 4:30 PMWithdraw Ksh2,000.00 from 654321 - BAKARI AGENCIES "
                "New M-PESA balance is Ksh2,345.00. Transaction cost, Ksh29.00.")
SMS_AIRTIME = ("SJA1B2C3D4 confirmed.You bought Ksh100.00 of airtime on 1/10/26 at 8:15 AM."
               "New M-PESA balance is Ksh4,900.00. Transaction cost, Ksh0.00.")


class SmsTests(unittest.TestCase):
    def test_paid_to_merchant(self):
        p = parse_sms(SMS_PAID)
        self.assertEqual((p.ref, p.kind, p.amount, p.category), ("SJA1B2C3D5", "expense", 1250.0, "shopping"))
        self.assertEqual(p.counterparty, "NAIVAS SUPERMARKET")
        self.assertEqual(p.occurred_on, date(2026, 10, 1))

    def test_send_money_with_fee(self):
        p = parse_sms(SMS_SENT)
        self.assertEqual((p.category, p.fee, p.counterparty), ("transfers", 13.0, "JANE DOE 0722111111"))

    def test_paybill(self):
        p = parse_sms(SMS_BILL)
        self.assertEqual((p.category, p.counterparty), ("bills", "KPLC PREPAID"))

    def test_received_is_income(self):
        p = parse_sms(SMS_RECEIVED)
        self.assertEqual((p.kind, p.amount, p.counterparty), ("income", 2000.0, "JOHN DOE 0712345678"))

    def test_withdrawal_and_airtime(self):
        self.assertEqual(parse_sms(SMS_WITHDRAW).category, "cash")
        self.assertEqual(parse_sms(SMS_WITHDRAW).counterparty, "654321 - BAKARI AGENCIES")
        self.assertEqual(parse_sms(SMS_AIRTIME).category, "airtime")

    def test_not_an_mpesa_message(self):
        with self.assertRaises(ValueError):
            parse_sms("Hi, are we still meeting at 5?")

    def test_parse_many_messages_pasted_together(self):
        parsed, failed = parse_messages("\n".join([SMS_PAID, SMS_SENT, SMS_RECEIVED]))
        self.assertEqual([p.ref for p in parsed], ["SJA1B2C3D5", "SJA1B2C3D9", "SJA1B2C3D8"])
        self.assertEqual(failed, [])


class SmsCommandTests(LedgerCase):
    def test_sms_command_records_fee_and_skips_repeats(self):
        msg_file = Path(self.tmp.name) / "sms.txt"
        msg_file.write_text("\n".join([SMS_SENT, SMS_RECEIVED]), encoding="utf-8")
        self.run_cli("sms", "--file", str(msg_file))
        output = self.run_cli("sms", "--file", str(msg_file))
        self.assertIn("already recorded", output)
        rows = self.ledger.transactions()
        self.assertEqual(sorted((t.kind, t.category, t.amount) for t in rows),
                         [("expense", "fees", 13.0), ("expense", "transfers", 800.0),
                          ("income", "income", 2000.0)])


class StatementTests(LedgerCase):
    def test_reads_only_completed_money_out(self):
        rows = read_statement(FIXTURE)
        receipts = [r.receipt for r in rows]
        self.assertEqual(len(rows), 6)
        self.assertNotIn("SJA1B2C3E0", receipts)  # failed
        self.assertNotIn("SJA1B2C3D8", receipts)  # money in
        self.assertEqual(sum(r.amount for r in rows), 4655.0)

    def test_guess_category(self):
        self.assertEqual(guess_category("Pay Bill Charge"), "fees")
        self.assertEqual(guess_category("Merchant Payment to 1 - SHOP"), "shopping")
        self.assertEqual(guess_category("Something unusual"), "other")

    def test_import_is_idempotent(self):
        self.run_cli("import", str(FIXTURE))
        self.run_cli("import", str(FIXTURE))
        self.assertEqual(len(self.ledger.transactions()), 6)

    def test_dry_run_saves_nothing(self):
        self.run_cli("import", str(FIXTURE), "--dry-run")
        self.assertEqual(self.ledger.transactions(), [])

    def test_missing_columns_rejected(self):
        bad = Path(self.tmp.name) / "bad.csv"
        bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_statement(bad)


class ReportTests(LedgerCase):
    def setUp(self):
        super().setUp()
        add = self.ledger.add
        add(30000, "salary", occurred_on=date(2026, 9, 28), kind="income")
        add(1000, "food", occurred_on=date(2026, 9, 5))
        add(500, "transport", occurred_on=date(2026, 9, 6))
        add(30000, "salary", occurred_on=date(2026, 10, 28), kind="income")
        add(1500, "food", occurred_on=date(2026, 10, 5))
        add(200, "airtime", occurred_on=date(2026, 10, 7))

    def test_cash_flow(self):
        flow = reports.cash_flow(self.ledger, date(2026, 10, 1), months=3)
        self.assertEqual([r["month"] for r in flow], ["2026-08", "2026-09", "2026-10"])
        self.assertEqual(flow[1], {"month": "2026-09", "income": 30000, "expense": 1500, "net": 28500})

    def test_top_categories(self):
        self.assertEqual(reports.top_categories(self.ledger, 2026, 10, n=1), [("food", 1500)])

    def test_month_over_month(self):
        rows = {r["category"]: r for r in reports.month_over_month(self.ledger, 2026, 10)}
        self.assertEqual(rows["food"]["change_pct"], 50.0)
        self.assertIsNone(rows["airtime"]["change_pct"])
        self.assertEqual(rows["transport"]["change"], -500)


class CliTests(LedgerCase):
    def test_add_warns_when_over_budget(self):
        self.ledger.set_budget("food", 1000)
        self.assertIn("over budget by KES 500.00", self.run_cli("add", "1500", "food"))

    def test_add_gives_heads_up_near_limit(self):
        self.ledger.set_budget("food", 1000)
        self.assertIn("Heads up", self.run_cli("add", "850", "food"))

    def test_income_transfer_and_balances(self):
        self.run_cli("account", "add", "bank", "--kind", "bank", "--opening", "5000")
        self.run_cli("income", "20000", "salary", "-a", "bank")
        self.run_cli("transfer", "3000", "bank", "mpesa")
        output = self.run_cli("account")
        self.assertIn("KES 22,000.00", output)  # bank
        self.assertIn("KES 3,000.00", output)   # mpesa

    def test_summary_shows_income_and_net(self):
        self.run_cli("income", "10000", "-d", "2026-10-02")
        self.run_cli("add", "2500", "rent", "-d", "2026-10-03")
        output = self.run_cli("summary", "-m", "2026-10")
        self.assertIn("KES 7,500.00", output)

    def test_errors_return_non_zero(self):
        self.run_cli("delete", "99", expect=1)
        self.run_cli("add", "100", "food", "-a", "nowhere", expect=1)

    def test_recurring_runs_on_next_command(self):
        self.run_cli("recurring", "add", "expense", "15000", "rent", "--day", "1", "--start", "2026-01-01")
        output = self.run_cli("list", "-c", "rent")
        self.assertIn("Recurring: added", output)

    def test_goal_commands(self):
        self.run_cli("goal", "add", "laptop", "60000")
        self.assertIn("25%", self.run_cli("goal", "save", "laptop", "15000"))
        self.assertIn("laptop", self.run_cli("goal"))

    def test_report_runs(self):
        self.run_cli("add", "100", "food", "-d", "2026-10-01")
        self.assertIn("Cash flow", self.run_cli("report", "-m", "2026-10"))


if __name__ == "__main__":
    unittest.main()
