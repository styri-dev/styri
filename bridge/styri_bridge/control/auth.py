"""The local admin: one password, scrypt-hashed, and cookie sessions.

Standard library only. Sessions live in memory, so a restart logs everyone out.
The websockets server only parses GET, so login happens over the WebSocket and
a single-use ticket turns it into an HttpOnly cookie (GET /api/session).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict
from pathlib import Path

ADMIN = "admin"
ANONYMOUS = "anonymous"
MIN_PASSWORD = 8
COOKIE = "styri_session"
TICKET_SECONDS = 30.0
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60.0

# scrypt cost: 2**14 * 8 * 128 bytes = 16 MiB per hash.
_N, _R, _P = 2**14, 8, 1


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = encoded.split("$")
        expected = _unb64(digest)
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return scheme == "scrypt" and hmac.compare_digest(actual, expected)


def _key(token: str) -> str:
    """Tokens are kept only as hashes."""
    return hashlib.sha256(token.encode()).hexdigest()


class Admin:
    def __init__(self, hash_file: str | None, session_hours: float = 8.0, env: dict | None = None,
                 clock=time.monotonic):
        env = os.environ if env is None else env
        self.file = Path(hash_file) if hash_file else None
        self.lifetime = session_hours * 3600
        self.clock = clock
        self._hash: str | None = None
        if env.get("STYRI_ADMIN_PASSWORD"):
            self._hash = hash_password(env["STYRI_ADMIN_PASSWORD"])
        elif self.file and self.file.is_file():
            self._hash = self.file.read_text(encoding="utf-8").strip() or None
        self._sessions: dict[str, float] = {}  # token hash -> last used
        self._tickets: dict[str, tuple[str, float]] = {}  # ticket hash -> token, expires
        self._failures: dict[str, list] = defaultdict(lambda: [0, 0.0])  # client -> count, locked until

    @property
    def needs_setup(self) -> bool:
        return self._hash is None

    def setup(self, password: str) -> None:
        """First run only. Raises ValueError with a reason for the operator."""
        if not self.needs_setup:
            raise ValueError("the admin password is already set")
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"use at least {MIN_PASSWORD} characters")
        encoded = hash_password(password)
        if self.file:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(encoded + "\n")
        self._hash = encoded

    def locked(self, client: str) -> float:
        """Seconds until this client may try again; 0 if it may."""
        return max(0.0, self._failures[client][1] - self.clock())

    def check(self, client: str, password: str) -> bool:
        ok = self._hash is not None and verify_password(password, self._hash)
        entry = self._failures[client]
        if ok:
            self._failures.pop(client, None)
        else:
            entry[0] += 1
            if entry[0] >= MAX_FAILURES:
                entry[0], entry[1] = 0, self.clock() + LOCKOUT_SECONDS
        return ok

    def open_session(self) -> tuple[str, str]:
        """A new session: (token, single-use ticket that sets its cookie)."""
        token, ticket = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = self.clock()
        self._sessions[_key(token)] = now
        self._tickets = {k: v for k, v in self._tickets.items() if v[1] > now}
        self._tickets[_key(ticket)] = (token, now + TICKET_SECONDS)
        return token, ticket

    def redeem(self, ticket: str) -> str | None:
        token, expires = self._tickets.pop(_key(ticket), (None, 0.0))
        return token if expires > self.clock() else None

    def valid(self, token: str | None, touch: bool = True) -> bool:
        """Is this session alive? Using it keeps it alive: it ends after inactivity."""
        if not token:
            return False
        key, now = _key(token), self.clock()
        last = self._sessions.get(key)
        if last is None or now - last > self.lifetime:
            self._sessions.pop(key, None)
            return False
        if touch:
            self._sessions[key] = now
        return True

    def close_session(self, token: str | None) -> None:
        if token:
            self._sessions.pop(_key(token), None)

    def cookie(self, token: str) -> str:
        return f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={int(self.lifetime)}"

    @staticmethod
    def clear_cookie() -> str:
        return f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"


def token_from(cookie_header: str | None) -> str | None:
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE and value:
            return value
    return None
