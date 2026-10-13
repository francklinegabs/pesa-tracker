"""Web dashboard, JSON API and M-Pesa SMS webhook.

`App.handle()` does all the work and knows nothing about the server it runs in:
`serve()` wraps it in the standard-library HTTP server for local use, and
`pesa.wsgi` wraps it for hosting (e.g. PythonAnywhere).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import webbrowser
from datetime import date
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import reports
from .db import Ledger
from .sms import record_messages

STATIC_DIR = Path(__file__).parent / "static"
TX_PATH = re.compile(r"^/api/transactions/(\d+)$")
MAX_BODY = 64 * 1024
SESSION_COOKIE = "pesa_session"
SESSION_SECONDS = 30 * 24 * 3600
SMS_TEXT_KEYS = ("text", "message", "body", "msg", "content")
# Explicit types: the Windows registry sometimes maps .js to text/plain.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

Response = tuple[int, list[tuple[str, str]], bytes]


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# -- request parsing helpers ---------------------------------------------------

def _one(query: dict, key: str) -> str | None:
    values = query.get(key)
    return values[0].strip() if values and values[0].strip() else None


def _date(value, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{field} must be a date like 2026-10-13") from None


def _month(value: str | None) -> tuple[int, int]:
    if value is None:
        today = date.today()
        return today.year, today.month
    try:
        year, month = (int(p) for p in value.split("-"))
        date(year, month, 1)
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, "month must look like 2026-10") from None
    return year, month


def _amount(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ApiError(HTTPStatus.BAD_REQUEST, "amount must be a number") from None


def _tx_fields(body: dict, partial: bool) -> dict:
    """Pick and convert the transaction fields present in a JSON body."""
    fields = {}
    if "amount" in body or not partial:
        fields["amount"] = _amount(body.get("amount"))
    for key in ("kind", "category", "note", "account"):
        if key in body and body[key] is not None:
            fields[key] = str(body[key])
    if "date" in body:
        when = _date(body["date"], "date")
        if when or not partial:
            fields["occurred_on"] = when
    if "to_account" in body:
        fields["to_account"] = str(body["to_account"]) if body["to_account"] else None
    if fields.get("kind") == "transfer" and not fields.get("category"):
        fields["category"] = "transfer"
    if "kind" in fields and fields["kind"] != "transfer":
        fields["to_account"] = None
    return fields


def _json_body(body: bytes) -> dict:
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApiError(HTTPStatus.BAD_REQUEST, "body must be JSON") from None
    if not isinstance(data, dict):
        raise ApiError(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
    return data


def sms_text_from_request(content_type: str, body: bytes) -> str:
    """Pull the message text out of whatever an SMS-forwarding app sends.

    Accepts JSON ({"text": ...}, {"message": ...}, ...), a urlencoded form with the
    same keys, or the raw message as plain text.
    """
    raw = body.decode("utf-8", errors="replace")
    content_type = content_type.lower()
    if "json" in content_type or raw.lstrip().startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            for key in SMS_TEXT_KEYS:
                if isinstance(data.get(key), str):
                    return data[key]
            raise ApiError(HTTPStatus.BAD_REQUEST, f"JSON needs one of: {', '.join(SMS_TEXT_KEYS)}")
    if "x-www-form-urlencoded" in content_type:
        form = parse_qs(raw)
        for key in SMS_TEXT_KEYS:
            if form.get(key):
                return form[key][0]
        raise ApiError(HTTPStatus.BAD_REQUEST, f"form needs one of: {', '.join(SMS_TEXT_KEYS)}")
    return raw


# -- API routes ----------------------------------------------------------------

def summary(ledger: Ledger, year: int, month: int) -> dict:
    spending = ledger.month_totals(year, month, "expense")
    income = sum(ledger.month_totals(year, month, "income").values())
    budgets = ledger.budgets
    categories = [
        {"category": c, "amount": spending.get(c, 0.0), "budget": budgets.get(c)}
        for c in set(spending) | set(budgets)
    ]
    categories.sort(key=lambda r: (-r["amount"], r["category"]))
    expense = sum(spending.values())
    return {
        "month": f"{year}-{month:02d}",
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "categories": categories,
        "accounts": ledger.balances(),
        "goals": ledger.goals(),
    }


def route(ledger: Ledger, method: str, path: str, query: dict, body: dict | None):
    """Handle one API call from the dashboard. Returns (status, payload)."""
    if path == "/api/summary" and method == "GET":
        ledger.generate_due()  # keeps recurring items current when hosted
        return HTTPStatus.OK, summary(ledger, *_month(_one(query, "month")))

    if path == "/api/cashflow" and method == "GET":
        year, month = _month(_one(query, "month"))
        months = min(max(int(_one(query, "months") or 6), 1), 24)
        return HTTPStatus.OK, reports.cash_flow(ledger, date(year, month, 1), months)

    if path == "/api/accounts" and method == "GET":
        return HTTPStatus.OK, ledger.balances()

    if path == "/api/categories" and method == "GET":
        return HTTPStatus.OK, ledger.categories()

    if path == "/api/sms/paste" and method == "POST":
        return HTTPStatus.OK, record_messages(ledger, str((body or {}).get("text", "")))

    if path == "/api/transactions":
        if method == "GET":
            rows = ledger.transactions(
                since=_date(_one(query, "since"), "since"),
                until=_date(_one(query, "until"), "until"),
                category=_one(query, "category"),
                kind=_one(query, "kind"),
                account=_one(query, "account"),
                search=_one(query, "q"),
            )
            return HTTPStatus.OK, [t.to_dict() for t in reversed(rows)]
        if method == "POST":
            fields = _tx_fields(body or {}, partial=False)
            fields.setdefault("category", "")
            t = ledger.add(**fields)
            return HTTPStatus.CREATED, t.to_dict()

    match = TX_PATH.match(path)
    if match:
        tx_id = int(match.group(1))
        if method == "GET":
            return HTTPStatus.OK, ledger.get(tx_id).to_dict()
        if method == "PUT":
            return HTTPStatus.OK, ledger.update(tx_id, **_tx_fields(body or {}, partial=True)).to_dict()
        if method == "DELETE":
            return HTTPStatus.OK, ledger.delete(tx_id).to_dict()

    raise ApiError(HTTPStatus.NOT_FOUND, f"no route for {method} {path}")


# -- the application -----------------------------------------------------------

def _json(status, payload, headers=()) -> Response:
    return int(status), [("Content-Type", "application/json"), *headers], json.dumps(payload).encode("utf-8")


def _redirect(location: str, headers=()) -> Response:
    return int(HTTPStatus.SEE_OTHER), [("Location", location), *headers], b""


def _static(name: str) -> Response:
    target = (STATIC_DIR / name).resolve()
    if STATIC_DIR.resolve() not in target.parents or not target.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "not found")
    ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
    return int(HTTPStatus.OK), [("Content-Type", ctype)], target.read_bytes()


class App:
    """The whole web app. `password` protects the dashboard; `sms_token` enables the SMS webhook."""

    def __init__(self, db_path: Path | str, password: str | None = None,
                 sms_token: str | None = None) -> None:
        self.db_path = db_path
        self.password = password or None
        self.sms_token = sms_token or None
        Ledger(db_path).close()  # create / migrate the database before any requests

    # sessions: a signed expiry time in an HttpOnly cookie

    def _session_value(self, expires: int) -> str:
        mac = hmac.new(self.password.encode(), f"pesa-session:{expires}".encode(), hashlib.sha256)
        return f"{expires}.{mac.hexdigest()}"

    def _logged_in(self, cookie_header: str | None) -> bool:
        if not self.password:
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header or "")
        except CookieError:
            return False
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return False
        expires = morsel.value.partition(".")[0]
        if not expires.isdigit() or int(expires) < time.time():
            return False
        return hmac.compare_digest(self._session_value(int(expires)), morsel.value)

    def _cookie(self, value: str, max_age: int, secure: bool) -> tuple[str, str]:
        flags = f"Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
        return "Set-Cookie", f"{SESSION_COOKIE}={value}; {flags}"

    # entry point

    def handle(self, method: str, path: str, query: str, headers: dict[str, str],
               body: bytes, secure: bool = False) -> Response:
        """Answer one request. `headers` has lower-case names."""
        try:
            if len(body) > MAX_BODY:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
            if path == "/api/sms":
                return self._sms_webhook(method, query, headers, body)
            if path == "/login":
                return self._login(method, body, secure)
            if path == "/logout":
                return _redirect("/login" if self.password else "/", [self._cookie("", 0, secure)])
            if path.startswith("/static/"):
                if method != "GET":
                    raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")
                return _static(path.removeprefix("/static/"))

            logged_in = self._logged_in(headers.get("cookie"))
            if path.startswith("/api/"):
                if not logged_in:
                    raise ApiError(HTTPStatus.UNAUTHORIZED, "please log in")
                data = None
                if method in ("POST", "PUT"):
                    # Requiring JSON means a form on another site can't post here (CSRF).
                    if "application/json" not in headers.get("content-type", ""):
                        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "send JSON")
                    data = _json_body(body)
                with Ledger(self.db_path) as ledger:
                    status, payload = route(ledger, method, path, parse_qs(query), data)
                return _json(status, payload)

            if path in ("/", "/index.html") and method == "GET":
                return _static("index.html") if logged_in else _redirect("/login")
            raise ApiError(HTTPStatus.NOT_FOUND, "not found")
        except ApiError as exc:
            return _json(exc.status, {"error": exc.message})
        except LookupError as exc:
            return _json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            return _json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _login(self, method: str, body: bytes, secure: bool) -> Response:
        if not self.password:
            return _redirect("/")
        if method == "GET":
            return _static("login.html")
        if method != "POST":
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")
        supplied = (parse_qs(body.decode("utf-8", errors="replace")).get("password") or [""])[0]
        if not hmac.compare_digest(supplied.encode(), self.password.encode()):
            time.sleep(1)  # slow down password guessing
            return _redirect("/login?error=1")
        expires = int(time.time()) + SESSION_SECONDS
        return _redirect("/", [self._cookie(self._session_value(expires), SESSION_SECONDS, secure)])

    def _sms_webhook(self, method: str, query: str, headers: dict[str, str], body: bytes) -> Response:
        """Receives M-Pesa SMS from a forwarding app on the phone."""
        if method != "POST":
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "POST the SMS text here")
        if not self.sms_token:
            raise ApiError(HTTPStatus.FORBIDDEN, "SMS webhook is off: set PESA_SMS_TOKEN")
        auth = headers.get("authorization", "")
        supplied = (_one(parse_qs(query), "token") or headers.get("x-pesa-token")
                    or (auth[7:] if auth.lower().startswith("bearer ") else ""))
        if not hmac.compare_digest(supplied.encode(), self.sms_token.encode()):
            raise ApiError(HTTPStatus.UNAUTHORIZED, "wrong or missing token")
        text = sms_text_from_request(headers.get("content-type", ""), body)
        with Ledger(self.db_path) as ledger:
            result = record_messages(ledger, text)
        # Always 200 for readable requests, even non-M-Pesa texts, so the phone doesn't keep retrying.
        return _json(HTTPStatus.OK, result)


# -- local server --------------------------------------------------------------

def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pesa-tracker"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def do_GET(self):
            self._dispatch()

        do_POST = do_PUT = do_DELETE = do_GET

        def _dispatch(self) -> None:
            url = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(length, MAX_BODY + 1)) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, extra, data = app.handle(self.command, url.path, url.query, headers, body)
            self.send_response(status)
            for name, value in extra:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def make_server(db_path: Path | str, host: str = "127.0.0.1", port: int = 8765,
                password: str | None = None, sms_token: str | None = None) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1") and not password:
        raise ValueError("set PESA_PASSWORD before making the dashboard reachable from other devices")
    app = App(db_path, password, sms_token)
    return ThreadingHTTPServer((host, port), make_handler(app))


def serve(db_path: Path | str, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          password: str | None = None, sms_token: str | None = None) -> None:
    server = make_server(db_path, host, port, password, sms_token)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"pesa dashboard running at {url}  (Ctrl+C to stop)")
    if sms_token:
        print(f"SMS webhook: POST {url}api/sms?token=<your PESA_SMS_TOKEN>")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
