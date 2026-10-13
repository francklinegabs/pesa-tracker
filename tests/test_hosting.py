import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

from pesa.db import Ledger
from pesa.web import App
from pesa.wsgi import make_wsgi_app

SMS = ("SJA1B2C3D5 Confirmed. Ksh1,250.00 paid to NAIVAS SUPERMARKET. on 1/10/26 at 12:40 PM."
       "New M-PESA balance is Ksh3,650.00. Transaction cost, Ksh0.00.")
SMS_WITH_FEE = ("SJA1B2C3D9 Confirmed. Ksh800.00 sent to JANE DOE 0722111111 on 4/10/26 at 10:05 AM. "
                "New M-PESA balance is Ksh4,345.00. Transaction cost, Ksh13.00.")
TOKEN = "s3cret-token-for-tests"


class HostedAppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "pesa.db"
        self.app = App(self.db, password="hunter2", sms_token=TOKEN)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method, path, query="", body=b"", headers=None, secure=False):
        return self.app.handle(method, path, query, headers or {}, body, secure)

    def login(self) -> str:
        with mock.patch("pesa.web.time.sleep"):
            status, headers, _ = self.call("POST", "/login", body=b"password=hunter2")
        self.assertEqual(status, 303)
        cookie = dict(headers)["Set-Cookie"]
        return cookie.split(";")[0]

    def transactions(self):
        with Ledger(self.db) as ledger:
            return ledger.transactions()


class LoginTests(HostedAppCase):
    def test_pages_and_api_need_login(self):
        status, headers, _ = self.call("GET", "/")
        self.assertEqual((status, dict(headers)["Location"]), (303, "/login"))
        self.assertEqual(self.call("GET", "/api/summary")[0], 401)

    def test_login_page_and_static_files_are_public(self):
        self.assertEqual(self.call("GET", "/login")[0], 200)
        self.assertEqual(self.call("GET", "/static/style.css")[0], 200)

    def test_wrong_password(self):
        with mock.patch("pesa.web.time.sleep") as sleep:
            status, headers, _ = self.call("POST", "/login", body=b"password=nope")
        self.assertEqual(dict(headers)["Location"], "/login?error=1")
        self.assertNotIn("Set-Cookie", dict(headers))
        sleep.assert_called_once()

    def test_session_cookie_grants_access(self):
        cookie = self.login()
        self.assertEqual(self.call("GET", "/", headers={"cookie": cookie})[0], 200)
        self.assertEqual(self.call("GET", "/api/summary", headers={"cookie": cookie})[0], 200)

    def test_cookie_flags(self):
        with mock.patch("pesa.web.time.sleep"):
            _, headers, _ = self.call("POST", "/login", body=b"password=hunter2", secure=True)
        cookie = dict(headers)["Set-Cookie"]
        for flag in ("HttpOnly", "SameSite=Lax", "Secure"):
            self.assertIn(flag, cookie)

    def test_forged_or_expired_cookie_rejected(self):
        for value in ("pesa_session=9999999999.deadbeef", "pesa_session=1.abc", "pesa_session=junk"):
            self.assertEqual(self.call("GET", "/api/summary", headers={"cookie": value})[0], 401, value)

    def test_logout_clears_cookie(self):
        _, headers, _ = self.call("GET", "/logout")
        self.assertIn("Max-Age=0", dict(headers)["Set-Cookie"])

    def test_api_writes_must_be_json(self):
        cookie = self.login()
        status, _, _ = self.call("POST", "/api/transactions", body=b"amount=5&category=food",
                                 headers={"cookie": cookie,
                                          "content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 415)

    def test_paste_sms_from_dashboard(self):
        cookie = self.login()
        status, _, data = self.call("POST", "/api/sms/paste", body=json.dumps({"text": SMS}).encode(),
                                    headers={"cookie": cookie, "content-type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(data)["added"]), 1)

    def test_no_password_means_open_local_mode(self):
        app = App(self.db)
        self.assertEqual(app.handle("GET", "/", "", {}, b"")[0], 200)
        self.assertEqual(app.handle("GET", "/login", "", {}, b"")[0], 303)


class SmsWebhookTests(HostedAppCase):
    def post_sms(self, body, content_type="application/json", query=f"token={TOKEN}", headers=None):
        return self.call("POST", "/api/sms", query=query, body=body,
                         headers={"content-type": content_type, **(headers or {})})

    def test_json_body(self):
        status, _, data = self.post_sms(json.dumps({"from": "MPESA", "text": SMS}).encode())
        self.assertEqual(status, 200)
        self.assertEqual([t["category"] for t in json.loads(data)["added"]], ["shopping"])

    def test_form_body_and_plain_text(self):
        self.post_sms(urlencode({"message": SMS}).encode(), "application/x-www-form-urlencoded")
        self.post_sms(SMS_WITH_FEE.encode(), "text/plain")
        self.assertEqual(sorted(t.category for t in self.transactions()), ["fees", "shopping", "transfers"])

    def test_token_in_header_or_bearer(self):
        body = json.dumps({"text": SMS}).encode()
        self.assertEqual(self.post_sms(body, query="", headers={"x-pesa-token": TOKEN})[0], 200)
        self.assertEqual(self.post_sms(body, query="", headers={"authorization": f"Bearer {TOKEN}"})[0], 200)

    def test_wrong_or_missing_token(self):
        body = json.dumps({"text": SMS}).encode()
        self.assertEqual(self.post_sms(body, query="token=wrong")[0], 401)
        self.assertEqual(self.post_sms(body, query="")[0], 401)
        self.assertEqual(self.transactions(), [])

    def test_webhook_off_without_token(self):
        app = App(self.db, password="hunter2")
        status, _, _ = app.handle("POST", "/api/sms", f"token={TOKEN}", {}, SMS.encode())
        self.assertEqual(status, 403)

    def test_same_sms_twice_is_recorded_once(self):
        body = json.dumps({"text": SMS}).encode()
        self.post_sms(body)
        _, _, data = self.post_sms(body)
        self.assertEqual(json.loads(data)["skipped"], ["SJA1B2C3D5"])
        self.assertEqual(len(self.transactions()), 1)

    def test_non_mpesa_text_is_ignored_with_200(self):
        status, _, data = self.post_sms(json.dumps({"text": "Your OTP is 1234"}).encode())
        self.assertEqual((status, json.loads(data)["unreadable"]), (200, 1))

    def test_json_without_text_field(self):
        self.assertEqual(self.post_sms(json.dumps({"foo": "bar"}).encode())[0], 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.call("GET", "/api/sms", query=f"token={TOKEN}")[0], 405)


class WsgiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "pesa.db"

    def tearDown(self):
        self.tmp.cleanup()

    def wsgi(self, app, method, path, body=b"", query="", content_type="application/json"):
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
                   "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": content_type,
                   "wsgi.input": io.BytesIO(body)}
        setup_testing_defaults(environ)
        captured = {}

        def start_response(status, headers):
            captured["status"], captured["headers"] = status, dict(headers)

        data = b"".join(app(environ, start_response))
        return captured["status"], captured["headers"], data

    def test_requires_password(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                make_wsgi_app(self.db)

    def test_reads_settings_from_environment(self):
        env = {"PESA_DB": str(self.db), "PESA_PASSWORD": "pw", "PESA_SMS_TOKEN": TOKEN}
        with mock.patch.dict("os.environ", env):
            app = make_wsgi_app()
        status, headers, _ = self.wsgi(app, "GET", "/")
        self.assertEqual((status, headers["Location"]), ("303 See Other", "/login"))
        status, _, data = self.wsgi(app, "POST", "/api/sms", json.dumps({"text": SMS}).encode(),
                                    query=f"token={TOKEN}")
        self.assertEqual(status, "200 OK")
        self.assertEqual(len(json.loads(data)["added"]), 1)
        self.assertTrue(self.db.exists())

    def test_https_sets_secure_cookie(self):
        app = make_wsgi_app(self.db, password="pw")
        environ_body = b"password=pw"
        with mock.patch("pesa.web.time.sleep"):
            environ = {"REQUEST_METHOD": "POST", "PATH_INFO": "/login", "QUERY_STRING": "",
                       "CONTENT_LENGTH": str(len(environ_body)),
                       "CONTENT_TYPE": "application/x-www-form-urlencoded",
                       "wsgi.input": io.BytesIO(environ_body), "HTTP_X_FORWARDED_PROTO": "https"}
            setup_testing_defaults(environ)
            headers = {}
            app(environ, lambda s, h: headers.update(h))
        self.assertIn("Secure", headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main()
