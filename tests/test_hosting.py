import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlparse
from wsgiref.util import setup_testing_defaults

from pesa.db import Ledger
from pesa.users import UserStore, check_password, hash_password
from pesa.web import App
from pesa.wsgi import make_wsgi_app

SMS = ("SJA1B2C3D5 Confirmed. Ksh1,250.00 paid to NAIVAS SUPERMARKET. on 1/10/26 at 12:40 PM."
       "New M-PESA balance is Ksh3,650.00. Transaction cost, Ksh0.00.")
SMS_WITH_FEE = ("SJA1B2C3D9 Confirmed. Ksh800.00 sent to JANE DOE 0722111111 on 4/10/26 at 10:05 AM. "
                "New M-PESA balance is Ksh4,345.00. Transaction cost, Ksh13.00.")
JSON = {"content-type": "application/json"}


class AppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = App(self.dir)
        patcher = mock.patch("pesa.web.time.sleep")  # failed logins sleep; not in tests
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method, path, query="", body=b"", headers=None, secure=False):
        return self.app.handle(method, path, query, headers or {}, body, secure)

    def signup(self, username="wanjiru", password="mpesa-pass-1", confirm=None):
        form = {"username": username, "password": password, "confirm": confirm or password}
        return self.call("POST", "/signup", body=urlencode(form).encode())

    def cookie_from(self, response) -> str:
        return dict(response[1])["Set-Cookie"].split(";")[0]

    def as_user(self, username="wanjiru", password="mpesa-pass-1") -> dict:
        return {"cookie": self.cookie_from(self.signup(username, password)), **JSON}

    def get_json(self, path, headers):
        status, _, data = self.call("GET", path, headers=headers)
        self.assertEqual(status, 200, data)
        return json.loads(data)

    def post_json(self, path, payload, headers):
        status, _, data = self.call("POST", path, body=json.dumps(payload).encode(), headers=headers)
        return status, json.loads(data)


class PasswordHashTests(unittest.TestCase):
    def test_hash_and_check(self):
        stored = hash_password("s3cret-pass", rounds=1000)
        self.assertTrue(stored.startswith("pbkdf2_sha256$1000$"))
        self.assertTrue(check_password("s3cret-pass", stored))
        self.assertFalse(check_password("wrong", stored))
        self.assertFalse(check_password("s3cret-pass", "garbage"))

    def test_same_password_gets_different_salt(self):
        self.assertNotEqual(hash_password("abcdefgh", rounds=1000), hash_password("abcdefgh", rounds=1000))


class UserStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.users = UserStore(Path(self.tmp.name) / "users.db")

    def tearDown(self):
        self.users.close()
        self.tmp.cleanup()

    def test_create_and_authenticate(self):
        user = self.users.create("  Kamau ", "password123")
        self.assertEqual(user.username, "kamau")
        self.assertEqual(self.users.authenticate("KAMAU", "password123").id, user.id)
        self.assertIsNone(self.users.authenticate("kamau", "wrong-pass"))
        self.assertIsNone(self.users.authenticate("nobody", "password123"))

    def test_validation(self):
        for username, password in [("ab", "password123"), ("bad name", "password123"),
                                   ("x" * 33, "password123"), ("okname", "short")]:
            with self.assertRaises(ValueError, msg=username):
                self.users.create(username, password)

    def test_duplicate_username(self):
        self.users.create("amina", "password123")
        with self.assertRaises(ValueError):
            self.users.create("Amina", "different-pass")

    def test_sms_tokens_are_unique_and_replaceable(self):
        a = self.users.create("amina", "password123")
        b = self.users.create("baraka", "password123")
        self.assertNotEqual(a.sms_token, b.sms_token)
        new = self.users.new_sms_token(a.id)
        self.assertIsNone(self.users.by_sms_token(a.sms_token))
        self.assertEqual(self.users.by_sms_token(new).id, a.id)
        self.assertIsNone(self.users.by_sms_token(""))

    def test_change_password(self):
        user = self.users.create("amina", "password123")
        with self.assertRaises(ValueError):
            self.users.change_password(user.id, "wrong", "new-password")
        self.users.change_password(user.id, "password123", "new-password")
        self.assertIsNotNone(self.users.authenticate("amina", "new-password"))


class SignupAndLoginTests(AppCase):
    def test_pages_and_api_need_login(self):
        status, headers, _ = self.call("GET", "/")
        self.assertEqual((status, dict(headers)["Location"]), (303, "/login"))
        self.assertEqual(self.call("GET", "/api/summary")[0], 401)

    def test_public_pages(self):
        for path in ("/login", "/signup", "/static/style.css"):
            self.assertEqual(self.call("GET", path)[0], 200, path)

    def test_android_app_download(self):
        self.assertEqual(self.call("GET", "/app")[0], 404)
        (self.dir / "pesa-tracker.apk").write_bytes(b"PK fake apk")
        status, headers, data = self.call("GET", "/app")
        self.assertEqual((status, data), (200, b"PK fake apk"))
        self.assertEqual(dict(headers)["Content-Type"], "application/vnd.android.package-archive")

    def test_signup_logs_you_in(self):
        response = self.signup()
        self.assertEqual((response[0], dict(response[1])["Location"]), (303, "/"))
        headers = {"cookie": self.cookie_from(response)}
        self.assertEqual(self.call("GET", "/", headers=headers)[0], 200)
        self.assertEqual(self.get_json("/api/me", headers)["username"], "wanjiru")

    def test_signup_errors_go_back_to_form(self):
        cases = [("ab", "mpesa-pass-1", None, "username"),
                 ("wanjiru", "short", None, "at least 8"),
                 ("wanjiru", "mpesa-pass-1", "other-pass-2", "match")]
        for username, password, confirm, expected in cases:
            status, headers, _ = self.signup(username, password, confirm)
            location = dict(headers)["Location"]
            self.assertTrue(location.startswith("/signup?"), location)
            self.assertIn(expected, parse_qs(urlparse(location).query)["error"][0])
            self.assertNotIn("Set-Cookie", dict(headers))

    def test_username_taken(self):
        self.signup()
        _, headers, _ = self.signup("Wanjiru", "another-pass-9")
        self.assertIn("taken", dict(headers)["Location"])

    def test_login(self):
        self.signup()
        good = self.call("POST", "/login", body=b"username=wanjiru&password=mpesa-pass-1")
        self.assertEqual(dict(good[1])["Location"], "/")
        self.assertIn("pesa_session=", dict(good[1])["Set-Cookie"])
        bad = self.call("POST", "/login", body=b"username=wanjiru&password=nope")
        self.assertEqual(dict(bad[1])["Location"], "/login?error=1")
        self.sleep.assert_called_once()

    def test_cookie_flags(self):
        response = self.app.handle("POST", "/signup", "", {}, urlencode(
            {"username": "amina", "password": "mpesa-pass-1", "confirm": "mpesa-pass-1"}).encode(), True)
        cookie = dict(response[1])["Set-Cookie"]
        for flag in ("HttpOnly", "SameSite=Lax", "Secure", "Max-Age="):
            self.assertIn(flag, cookie)

    def test_forged_cookies_rejected(self):
        self.signup()
        for value in ("1.9999999999.deadbeef", "1.1.abc", "junk", "2.9999999999.x", "a.b.c"):
            status = self.call("GET", "/api/summary", headers={"cookie": f"pesa_session={value}"})[0]
            self.assertEqual(status, 401, value)

    def test_logout_clears_cookie(self):
        _, headers, _ = self.call("GET", "/logout")
        self.assertIn("Max-Age=0", dict(headers)["Set-Cookie"])

    def test_signup_can_be_closed(self):
        app = App(self.dir, allow_signup=False)
        status, headers, _ = app.handle("POST", "/signup", "", {}, b"username=x&password=y")
        self.assertEqual(dict(headers)["Location"], "/login?error=closed")

    def test_api_writes_must_be_json(self):
        headers = self.as_user()
        headers["content-type"] = "application/x-www-form-urlencoded"
        self.assertEqual(self.call("POST", "/api/transactions", body=b"amount=5", headers=headers)[0], 415)


class IsolationTests(AppCase):
    def test_each_user_only_sees_their_own_money(self):
        alice, bob = self.as_user("alice", "alice-pass-1"), self.as_user("bob", "bob-pass-12")
        self.post_json("/api/transactions", {"amount": 500, "category": "food"}, alice)
        self.post_json("/api/transactions", {"amount": 900, "category": "rent"}, bob)
        self.assertEqual([t["category"] for t in self.get_json("/api/transactions", alice)], ["food"])
        self.assertEqual([t["category"] for t in self.get_json("/api/transactions", bob)], ["rent"])

    def test_cannot_touch_another_users_transaction_by_id(self):
        alice, bob = self.as_user("alice", "alice-pass-1"), self.as_user("bob", "bob-pass-12")
        _, t = self.post_json("/api/transactions", {"amount": 500, "category": "food"}, alice)
        # Bob's database has no transaction with that id (or it is his own); Alice's stays untouched.
        self.call("DELETE", f"/api/transactions/{t['id']}", headers=bob)
        self.assertEqual(len(self.get_json("/api/transactions", alice)), 1)

    def test_first_account_adopts_existing_single_user_data(self):
        with Ledger(self.dir / "pesa.db") as ledger:
            ledger.add(1234, "old-data")
        first = self.as_user("owner", "owner-pass-1")
        second = self.as_user("guest", "guest-pass-1")
        self.assertEqual([t["category"] for t in self.get_json("/api/transactions", first)], ["old-data"])
        self.assertEqual(self.get_json("/api/transactions", second), [])
        self.assertFalse((self.dir / "pesa.db").exists())


class SettingsTests(AppCase):
    def test_me_shows_personal_sms_link(self):
        headers = self.as_user()
        me = self.get_json("/api/me", headers)
        self.assertTrue(me["sms_path"].startswith("/api/sms?token="))

    def test_new_sms_token(self):
        headers = self.as_user()
        old = self.get_json("/api/me", headers)["sms_path"]
        status, result = self.post_json("/api/me/sms-token", {}, headers)
        self.assertEqual(status, 200)
        self.assertNotEqual(result["sms_path"], old)
        old_token = parse_qs(urlparse(old).query)["token"][0]
        self.assertEqual(self.call("POST", "/api/sms", f"token={old_token}", body=SMS.encode())[0], 401)

    def test_change_password_signs_out_other_devices(self):
        laptop = self.as_user()
        phone = {"cookie": self.cookie_from(self.call(
            "POST", "/login", body=b"username=wanjiru&password=mpesa-pass-1")), **JSON}
        status, _ = self.post_json("/api/me/password", {"current": "wrong", "new": "new-pass-123"}, laptop)
        self.assertEqual(status, 400)
        status, headers, _ = self.call("POST", "/api/me/password", headers=laptop,
                                       body=json.dumps({"current": "mpesa-pass-1", "new": "new-pass-123"}).encode())
        self.assertEqual(status, 200)
        laptop["cookie"] = dict(headers)["Set-Cookie"].split(";")[0]
        self.assertEqual(self.call("GET", "/api/me", headers=laptop)[0], 200)
        self.assertEqual(self.call("GET", "/api/me", headers=phone)[0], 401)

    def test_paste_sms(self):
        headers = self.as_user()
        status, result = self.post_json("/api/sms/paste", {"text": SMS}, headers)
        self.assertEqual((status, len(result["added"])), (200, 1))


class SmsWebhookTests(AppCase):
    def setUp(self):
        super().setUp()
        self.headers = self.as_user()
        self.token = parse_qs(urlparse(self.get_json("/api/me", self.headers)["sms_path"]).query)["token"][0]

    def post_sms(self, body, content_type="application/json", query=None, headers=None):
        query = f"token={self.token}" if query is None else query
        return self.call("POST", "/api/sms", query=query, body=body,
                         headers={"content-type": content_type, **(headers or {})})

    def categories(self, headers=None):
        return sorted(t["category"] for t in self.get_json("/api/transactions", headers or self.headers))

    def test_json_body(self):
        status, _, data = self.post_sms(json.dumps({"from": "MPESA", "text": SMS}).encode())
        self.assertEqual(status, 200)
        self.assertEqual([t["category"] for t in json.loads(data)["added"]], ["shopping"])

    def test_form_body_and_plain_text(self):
        self.post_sms(urlencode({"message": SMS}).encode(), "application/x-www-form-urlencoded")
        self.post_sms(SMS_WITH_FEE.encode(), "text/plain")
        self.assertEqual(self.categories(), ["fees", "shopping", "transfers"])

    def test_token_in_header_or_bearer(self):
        body = json.dumps({"text": SMS}).encode()
        self.assertEqual(self.post_sms(body, query="", headers={"x-pesa-token": self.token})[0], 200)
        self.assertEqual(self.post_sms(body, query="", headers={"authorization": f"Bearer {self.token}"})[0], 200)

    def test_wrong_or_missing_token(self):
        body = json.dumps({"text": SMS}).encode()
        self.assertEqual(self.post_sms(body, query="token=wrong")[0], 401)
        self.assertEqual(self.post_sms(body, query="")[0], 401)
        self.assertEqual(self.categories(), [])

    def test_sms_goes_to_the_right_user(self):
        other = self.as_user("baraka", "baraka-pass-1")
        self.post_sms(json.dumps({"text": SMS}).encode())
        self.assertEqual(self.categories(), ["shopping"])
        self.assertEqual(self.categories(other), [])

    def test_same_sms_twice_is_recorded_once(self):
        body = json.dumps({"text": SMS}).encode()
        self.post_sms(body)
        _, _, data = self.post_sms(body)
        self.assertEqual(json.loads(data)["skipped"], ["SJA1B2C3D5"])

    def test_non_mpesa_text_is_ignored_with_200(self):
        status, _, data = self.post_sms(json.dumps({"text": "Your OTP is 1234"}).encode())
        self.assertEqual((status, json.loads(data)["unreadable"]), (200, 1))

    def test_json_without_text_field(self):
        self.assertEqual(self.post_sms(json.dumps({"foo": "bar"}).encode())[0], 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.call("GET", "/api/sms", query=f"token={self.token}")[0], 405)


class WsgiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def wsgi(self, app, method, path, body=b"", content_type="application/x-www-form-urlencoded", **extra):
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
                   "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": content_type,
                   "wsgi.input": io.BytesIO(body), **extra}
        setup_testing_defaults(environ)
        captured = {}

        def start_response(status, headers):
            captured["status"], captured["headers"] = status, dict(headers)

        data = b"".join(app(environ, start_response))
        return captured["status"], captured["headers"], data

    def test_reads_settings_from_environment(self):
        with mock.patch.dict("os.environ", {"PESA_DATA_DIR": str(self.dir), "PESA_ALLOW_SIGNUP": "0"}):
            app = make_wsgi_app()
        status, headers, _ = self.wsgi(app, "GET", "/")
        self.assertEqual((status, headers["Location"]), ("303 See Other", "/login"))
        _, headers, _ = self.wsgi(app, "POST", "/signup", b"username=a&password=b")
        self.assertEqual(headers["Location"], "/login?error=closed")
        self.assertTrue((self.dir / "users.db").exists())

    def test_signup_over_https_sets_secure_cookie(self):
        app = make_wsgi_app(self.dir, allow_signup=True)
        body = urlencode({"username": "amina", "password": "mpesa-pass-1", "confirm": "mpesa-pass-1"}).encode()
        _, headers, _ = self.wsgi(app, "POST", "/signup", body, HTTP_X_FORWARDED_PROTO="https")
        self.assertIn("Secure", headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main()
