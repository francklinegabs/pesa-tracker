import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from http.server import ThreadingHTTPServer

from pesa.db import Ledger
from pesa.users import UserStore
from pesa.web import App, make_handler


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        app = App(cls.tmp.name)
        with UserStore(app.users_path) as users:
            user = users.create("tester", "correct horse")
        cls.db = app.ledger_path(user)
        Ledger(cls.db).close()
        cls.cookie = app._session_cookie(user, secure=False)[1].split(";")[0]
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        with Ledger(self.db) as ledger:
            ledger.conn.executescript("DELETE FROM transactions; DELETE FROM budgets; DELETE FROM goals;"
                                      "DELETE FROM accounts WHERE name != 'mpesa';")

    def request(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Cookie": self.cookie})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.headers.get("Content-Type"), res.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.headers.get("Content-Type"), err.read()

    def api(self, method, path, body=None, raw=None):
        status, _, data = self.request(method, path, body, raw)
        return status, json.loads(data)

    # -- static files ---------------------------------------------------------

    def test_index_page_is_served(self):
        status, ctype, data = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/html"))
        self.assertIn(b"pesa", data)

    def test_javascript_has_right_type(self):
        status, ctype, _ = self.request("GET", "/static/app.js")
        self.assertEqual((status, ctype), (200, "text/javascript; charset=utf-8"))

    def test_path_traversal_is_blocked(self):
        for path in ("/static/../db.py", "/static/..%2fdb.py", "/static/missing.css"):
            self.assertEqual(self.request("GET", path)[0], 404, path)

    # -- transactions ---------------------------------------------------------

    def test_create_list_update_delete(self):
        status, created = self.api("POST", "/api/transactions",
                                   {"amount": "450", "category": "Food", "note": "lunch", "date": "2026-10-05"})
        self.assertEqual(status, 201)
        self.assertEqual((created["category"], created["amount"], created["account"]), ("food", 450, "mpesa"))

        status, rows = self.api("GET", "/api/transactions")
        self.assertEqual([r["id"] for r in rows], [created["id"]])

        status, updated = self.api("PUT", f"/api/transactions/{created['id']}", {"amount": 500, "date": ""})
        self.assertEqual((status, updated["amount"], updated["occurred_on"]), (200, 500, "2026-10-05"))

        status, _ = self.api("DELETE", f"/api/transactions/{created['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(self.api("GET", f"/api/transactions/{created['id']}")[0], 404)

    def test_transfer_via_api(self):
        with Ledger(self.db) as ledger:
            ledger.add_account("cash")
        status, t = self.api("POST", "/api/transactions",
                             {"kind": "transfer", "amount": 1000, "account": "mpesa", "to_account": "cash"})
        self.assertEqual((status, t["category"], t["to_account"]), (201, "transfer", "cash"))
        balances = {a["name"]: a["balance"] for a in self.api("GET", "/api/accounts")[1]}
        self.assertEqual(balances, {"cash": 1000, "mpesa": -1000})

    def test_changing_transfer_to_expense_clears_destination(self):
        with Ledger(self.db) as ledger:
            ledger.add_account("cash")
            t = ledger.transfer(300, "mpesa", "cash")
        status, updated = self.api("PUT", f"/api/transactions/{t.id}", {"kind": "expense", "category": "food"})
        self.assertEqual((status, updated["to_account"]), (200, None))

    def test_filters(self):
        with Ledger(self.db) as ledger:
            ledger.add(100, "food", "chapati", date(2026, 10, 1))
            ledger.add(200, "transport", "matatu", date(2026, 10, 2))
            ledger.add(5000, "salary", "", date(2026, 10, 3), kind="income")
        ids = lambda q: [r["note"] or r["category"] for r in self.api("GET", "/api/transactions?" + q)[1]]
        self.assertEqual(ids("q=chap"), ["chapati"])
        self.assertEqual(ids("kind=income"), ["salary"])
        self.assertEqual(ids("since=2026-10-02&kind=expense"), ["matatu"])
        self.assertEqual(ids("category=food"), ["chapati"])

    def test_validation_errors(self):
        cases = [
            {"amount": -5, "category": "food"},
            {"amount": "abc", "category": "food"},
            {"amount": 100, "category": ""},
            {"amount": 100, "category": "food", "account": "nowhere"},
            {"amount": 100, "category": "food", "date": "13/10/2026"},
            {"amount": 100, "kind": "transfer", "account": "mpesa", "to_account": "mpesa"},
        ]
        for body in cases:
            status, payload = self.api("POST", "/api/transactions", body)
            self.assertEqual(status, 400, body)
            self.assertIn("error", payload)

    def test_bad_json_and_unknown_route(self):
        self.assertEqual(self.api("POST", "/api/transactions", raw=b"{not json")[0], 400)
        self.assertEqual(self.api("POST", "/api/transactions", raw=b"[1, 2]")[0], 400)
        self.assertEqual(self.api("GET", "/api/nope")[0], 404)
        self.assertEqual(self.api("DELETE", "/api/transactions")[0], 404)

    # -- dashboard data -------------------------------------------------------

    def test_summary(self):
        with Ledger(self.db) as ledger:
            ledger.set_budget("food", 1000)
            ledger.set_budget("rent", 15000)
            ledger.add(1200, "food", occurred_on=date(2026, 10, 1))
            ledger.add(30000, "salary", occurred_on=date(2026, 10, 2), kind="income")
            ledger.add_goal("laptop", 60000)
        status, s = self.api("GET", "/api/summary?month=2026-10")
        self.assertEqual(status, 200)
        self.assertEqual((s["income"], s["expense"], s["net"]), (30000, 1200, 28800))
        cats = {c["category"]: c for c in s["categories"]}
        self.assertEqual(cats["food"], {"category": "food", "amount": 1200, "budget": 1000})
        self.assertEqual(cats["rent"]["amount"], 0)  # budget with no spending still shows
        self.assertEqual([g["name"] for g in s["goals"]], ["laptop"])
        self.assertEqual(self.api("GET", "/api/summary?month=2026-13")[0], 400)

    def test_cashflow(self):
        with Ledger(self.db) as ledger:
            ledger.add(500, "food", occurred_on=date(2026, 9, 10))
        status, flow = self.api("GET", "/api/cashflow?month=2026-10&months=3")
        self.assertEqual([r["month"] for r in flow], ["2026-08", "2026-09", "2026-10"])
        self.assertEqual(flow[1]["expense"], 500)

    def test_categories(self):
        with Ledger(self.db) as ledger:
            ledger.add(100, "food")
            ledger.set_budget("rent", 1000)
        self.assertEqual(self.api("GET", "/api/categories")[1], ["food", "rent"])


if __name__ == "__main__":
    unittest.main()
