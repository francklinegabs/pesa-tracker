"""WSGI entry point for hosting pesa-tracker online (PythonAnywhere, gunicorn, ...).

Optional environment variables (on PythonAnywhere: set them at the top of the WSGI file):

    PESA_DATA_DIR      folder for users.db and everyone's data (default: ~/.pesa)
    PESA_ALLOW_SIGNUP  set to 0 to stop new people creating accounts

then expose `application`:

    from pesa.wsgi import application
"""

from __future__ import annotations

import os
from http import HTTPStatus
from pathlib import Path

from .web import MAX_BODY, App


def make_wsgi_app(data_dir: Path | str | None = None, allow_signup: bool | None = None):
    data_dir = data_dir or os.environ.get("PESA_DATA_DIR") or Path.home() / ".pesa"
    if allow_signup is None:
        allow_signup = os.environ.get("PESA_ALLOW_SIGNUP", "1").strip().lower() not in ("0", "false", "no")
    app = App(data_dir, allow_signup)

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
