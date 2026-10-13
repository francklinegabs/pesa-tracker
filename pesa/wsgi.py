"""WSGI entry point for hosting pesa-tracker online (PythonAnywhere, gunicorn, ...).

Set these environment variables (on PythonAnywhere: at the top of the WSGI file):

    PESA_DB         path to the database file, e.g. /home/you/pesa.db
    PESA_PASSWORD   password for the dashboard (required)
    PESA_SMS_TOKEN  long random secret your phone sends with each SMS (optional)

then expose `application`:

    from pesa.wsgi import application
"""

from __future__ import annotations

import os
from http import HTTPStatus
from pathlib import Path

from .web import MAX_BODY, App


def make_wsgi_app(db_path: Path | str | None = None, password: str | None = None,
                  sms_token: str | None = None):
    password = password or os.environ.get("PESA_PASSWORD")
    if not password:
        raise RuntimeError("Set PESA_PASSWORD before hosting pesa-tracker online")
    db_path = db_path or os.environ.get("PESA_DB") or Path.home() / ".pesa" / "pesa.db"
    app = App(db_path, password, sms_token or os.environ.get("PESA_SMS_TOKEN"))

    def application(environ, start_response):
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        body = environ["wsgi.input"].read(min(length, MAX_BODY + 1)) if length > 0 else b""
        headers = {key[5:].replace("_", "-").lower(): value
                   for key, value in environ.items() if key.startswith("HTTP_")}
        if environ.get("CONTENT_TYPE"):
            headers["content-type"] = environ["CONTENT_TYPE"]
        secure = environ.get("wsgi.url_scheme") == "https" or headers.get("x-forwarded-proto") == "https"
        status, extra, data = app.handle(environ["REQUEST_METHOD"], environ.get("PATH_INFO") or "/",
                                         environ.get("QUERY_STRING", ""), headers, body, secure)
        start_response(f"{status} {HTTPStatus(status).phrase}", [
            *extra,
            ("Content-Length", str(len(data))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ])
        return [data]

    return application


def __getattr__(name):
    # `from pesa.wsgi import application` builds the app on first use, after the
    # hosting config has had a chance to set the environment variables.
    if name == "application":
        app = make_wsgi_app()
        globals()["application"] = app
        return app
    raise AttributeError(name)
