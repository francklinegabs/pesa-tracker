"""Local web dashboard and JSON API: python -m pesa serve"""

from __future__ import annotations

import json
import re
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import reports
from .db import Ledger

STATIC_DIR = Path(__file__).parent / "static"
TX_PATH = re.compile(r"^/api/transactions/(\d+)$")
MAX_BODY = 64 * 1024
# Explicit types: the Windows registry sometimes maps .js to text/plain.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


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


# -- routes --------------------------------------------------------------------

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
    """Handle one API call. Returns (status, payload)."""
    if path == "/api/summary" and method == "GET":
        return HTTPStatus.OK, summary(ledger, *_month(_one(query, "month")))

    if path == "/api/cashflow" and method == "GET":
        year, month = _month(_one(query, "month"))
        months = min(max(int(_one(query, "months") or 6), 1), 24)
        return HTTPStatus.OK, reports.cash_flow(ledger, date(year, month, 1), months)

    if path == "/api/accounts" and method == "GET":
        return HTTPStatus.OK, ledger.balances()

    if path == "/api/categories" and method == "GET":
        return HTTPStatus.OK, ledger.categories()

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


# -- HTTP plumbing -------------------------------------------------------------

def make_handler(db_path: Path | str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pesa-tracker"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            try:
                if not url.path.startswith("/api/"):
                    if method != "GET":
                        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")
                    return self._static(url.path)
                body = self._read_body() if method in ("POST", "PUT") else None
                with Ledger(db_path) as ledger:
                    status, payload = route(ledger, method, url.path, parse_qs(url.query), body)
                self._send_json(status, payload)
            except ApiError as exc:
                self._send_json(exc.status, {"error": exc.message})
            except LookupError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except (ValueError, TypeError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ApiError(HTTPStatus.BAD_REQUEST, "body must be JSON") from None
            if not isinstance(body, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
            return body

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("/", "/index.html") else path.removeprefix("/static/")
            target = (STATIC_DIR / name).resolve()
            if STATIC_DIR.resolve() not in target.parents or not target.is_file():
                raise ApiError(HTTPStatus.NOT_FOUND, "not found")
            ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            self._send(HTTPStatus.OK, target.read_bytes(), ctype)

        def _send_json(self, status: HTTPStatus, payload) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _send(self, status: HTTPStatus, data: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def make_server(db_path: Path | str, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    Ledger(db_path).close()  # create / migrate the database once, before any requests
    return ThreadingHTTPServer((host, port), make_handler(db_path))


def serve(db_path: Path | str, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = True) -> None:
    server = make_server(db_path, host, port)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"pesa dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
