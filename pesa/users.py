"""User accounts for the web app. Each user's money lives in their own database file."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 200
PBKDF2_ROUNDS = 240_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    sms_token     TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL
);
"""


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    sms_token: str


def hash_password(password: str, salt: bytes | None = None, rounds: int = PBKDF2_ROUNDS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, _ = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, bytes.fromhex(salt), int(rounds))
    return hmac.compare_digest(candidate, stored)


def validate_username(username: str) -> str:
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError("username must be 3-32 characters: letters, numbers, . _ or -")
    return username


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    if len(password) > MAX_PASSWORD:
        raise ValueError("password is too long")


# Spent on unknown usernames so a failed login takes as long either way.
_DUMMY_HASH = hash_password("not-a-real-password")


class UserStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "UserStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _user(self, row) -> User | None:
        return User(row["id"], row["username"], row["password_hash"], row["sms_token"]) if row else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create(self, username: str, password: str) -> User:
        username = validate_username(username)
        validate_password(password)
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO users (username, password_hash, sms_token, created_at) VALUES (?, ?, ?, ?)",
                    (username, hash_password(password), secrets.token_urlsafe(24),
                     datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            raise ValueError("that username is taken") from None
        return self.get(cur.lastrowid)

    def get(self, user_id: int) -> User | None:
        return self._user(self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def authenticate(self, username: str, password: str) -> User | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
        if row is None:
            check_password(password, _DUMMY_HASH)
            return None
        return self._user(row) if check_password(password, row["password_hash"]) else None

    def by_sms_token(self, token: str) -> User | None:
        if not token:
            return None
        row = self.conn.execute("SELECT * FROM users WHERE sms_token = ?", (token,)).fetchone()
        return self._user(row)

    def new_sms_token(self, user_id: int) -> str:
        token = secrets.token_urlsafe(24)
        with self.conn:
            self.conn.execute("UPDATE users SET sms_token = ? WHERE id = ?", (token, user_id))
        return token

    def change_password(self, user_id: int, current: str, new: str) -> User:
        user = self.get(user_id)
        if user is None or not check_password(current, user.password_hash):
            raise ValueError("current password is wrong")
        validate_password(new)
        with self.conn:
            self.conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                              (hash_password(new), user_id))
        return self.get(user_id)
