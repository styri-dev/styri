"""Local accounts: viewer, operator and admin, scrypt-hashed, with cookie sessions.

Standard library only. Accounts live in users.json next to the audit log, and
`styri users` writes it too, so the file is re-read when it changes. Sessions live
in memory, so a restart logs everyone out. The websockets server only parses GET,
so login happens over the WebSocket and a single-use ticket turns it into an
HttpOnly cookie (GET /api/session).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ADMIN = "admin"  # the top role, and the first account's name
OPERATOR = "operator"
VIEWER = "viewer"
ROLES = (VIEWER, OPERATOR, ADMIN)  # each can do what the one before can
ANONYMOUS = "anonymous"
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
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


# Checked against when the name doesn't exist, so timing doesn't reveal which names do.
_DUMMY = hash_password(secrets.token_hex(8))


def _key(token: str) -> str:
    """Tokens are kept only as hashes."""
    return hashlib.sha256(token.encode()).hexdigest()


def write_private(path: Path, text: str) -> None:
    """Whole or not at all, readable only by Styri."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    tmp.replace(path)


@dataclass(frozen=True)
class User:
    name: str
    role: str

    def can(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


class AccountError(ValueError):
    """Not allowed. The message is for the person doing it."""


class Accounts:
    def __init__(self, path: str | None, session_hours: float = 8.0, env: dict | None = None,
                 clock=time.monotonic):
        env = os.environ if env is None else env
        self.file = Path(path) if path else None
        self.lifetime = session_hours * 3600
        self.clock = clock
        self._users: dict[str, dict] = {}
        self._stamp: int | None = None
        self._load()
        self._migrate()
        if env.get("STYRI_ADMIN_PASSWORD"):
            self._users.setdefault(ADMIN, {}).update(hash=hash_password(env["STYRI_ADMIN_PASSWORD"]), role=ADMIN)
            self._save()
        self._sessions: dict[str, list] = {}  # token hash -> [name, last used]
        self._tickets: dict[str, tuple[str, float]] = {}  # ticket hash -> token, expires
        self._failures: dict[str, list] = defaultdict(lambda: [0, 0.0])  # client -> count, locked until

    # ---- the file ---------------------------------------------------------

    def _load(self) -> None:
        if self.file and self.file.is_file():
            self._stamp = self.file.stat().st_mtime_ns
            self._users = json.loads(self.file.read_text(encoding="utf-8"))["users"]

    def _fresh(self) -> None:
        """`styri users` may have changed the file."""
        if self.file and self.file.is_file() and self.file.stat().st_mtime_ns != self._stamp:
            self._load()

    def _save(self) -> None:
        if self.file:
            write_private(self.file, json.dumps({"users": self._users}, indent=1) + "\n")
            self._stamp = self.file.stat().st_mtime_ns

    def _migrate(self) -> None:
        """A password set before accounts existed becomes the admin account."""
        old = self.file.with_name("admin.hash") if self.file else None
        if old and old.is_file() and not self._users:
            self._users[ADMIN] = {"hash": old.read_text(encoding="utf-8").strip(), "role": ADMIN}
            self._save()
            old.unlink()

    # ---- accounts -----------------------------------------------------------

    @property
    def needs_setup(self) -> bool:
        self._fresh()
        return not self._users

    def get(self, name: str | None) -> User | None:
        self._fresh()
        entry = self._users.get(name or "")
        return User(name, entry["role"]) if entry else None

    def list(self) -> list[dict]:
        self._fresh()
        online = {s[0] for s in self._sessions.values() if self.clock() - s[1] <= self.lifetime}
        return [{"name": n, "role": u["role"], "last_login": u.get("last_login"), "active": n in online}
                for n, u in sorted(self._users.items())]

    def _admins(self) -> int:
        return sum(u["role"] == ADMIN for u in self._users.values())

    @staticmethod
    def _password(password: object) -> str:
        if not isinstance(password, str) or len(password) < MIN_PASSWORD:
            raise AccountError(f"use at least {MIN_PASSWORD} characters")
        return password

    @staticmethod
    def _role(role: object) -> str:
        if role not in ROLES:
            raise AccountError(f"role must be one of {', '.join(ROLES)}")
        return role

    def _existing(self, name: object) -> dict:
        self._fresh()
        if not isinstance(name, str) or name not in self._users:
            raise AccountError(f"no user {str(name)[:32]}")
        return self._users[name]

    def add(self, name: object, password: object, role: object) -> None:
        self._fresh()
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise AccountError("names are lower-case letters, digits, dots, dashes and underscores")
        if name in self._users:
            raise AccountError(f"{name} already exists")
        self._users[name] = {"hash": hash_password(self._password(password)), "role": self._role(role)}
        self._save()

    def setup(self, password: object) -> None:
        """First run only."""
        if not self.needs_setup:
            raise AccountError("the admin password is already set")
        self.add(ADMIN, password, ADMIN)

    def _keep_an_admin(self, entry: dict) -> None:
        if entry["role"] == ADMIN and self._admins() == 1:
            raise AccountError("this is the last admin: make someone else an admin first")

    def remove(self, name: str) -> None:
        self._keep_an_admin(self._existing(name))
        del self._users[name]
        self._save()
        self._end_sessions(name)

    def set_role(self, name: str, role: object) -> None:
        entry = self._existing(name)
        if self._role(role) != ADMIN:
            self._keep_an_admin(entry)
        entry["role"] = role
        self._save()

    def set_password(self, name: str, password: object) -> None:
        self._existing(name)["hash"] = hash_password(self._password(password))
        self._save()
        self._end_sessions(name)

    def _end_sessions(self, name: str) -> None:
        self._sessions = {k: v for k, v in self._sessions.items() if v[0] != name}

    # ---- logging in -----------------------------------------------------------

    def locked(self, client: str) -> float:
        """Seconds until this client may try again; 0 if it may."""
        return max(0.0, self._failures[client][1] - self.clock())

    def check(self, client: str, name: str, password: str) -> User | None:
        self._fresh()
        entry = self._users.get(name)
        right = verify_password(password, entry["hash"] if entry else _DUMMY)
        if entry is not None and right:
            self._failures.pop(client, None)
            entry["last_login"] = int(time.time())
            self._save()
            return User(name, entry["role"])
        failures = self._failures[client]
        failures[0] += 1
        if failures[0] >= MAX_FAILURES:
            failures[0], failures[1] = 0, self.clock() + LOCKOUT_SECONDS
        return None

    def open_session(self, name: str = ADMIN) -> tuple[str, str]:
        """A new session: (token, single-use ticket that sets its cookie)."""
        token, ticket = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = self.clock()
        self._sessions[_key(token)] = [name, now]
        self._tickets = {k: v for k, v in self._tickets.items() if v[1] > now}
        self._tickets[_key(ticket)] = (token, now + TICKET_SECONDS)
        return token, ticket

    def redeem(self, ticket: str) -> str | None:
        token, expires = self._tickets.pop(_key(ticket), (None, 0.0))
        return token if expires > self.clock() else None

    def user(self, token: str | None, touch: bool = True) -> User | None:
        """Who this session is. Using it keeps it alive: it ends after inactivity."""
        if not token:
            return None
        key, now = _key(token), self.clock()
        session = self._sessions.get(key)
        if session is None or now - session[1] > self.lifetime:
            self._sessions.pop(key, None)
            return None
        user = self.get(session[0])
        if user is None:  # removed in the terminal
            self._sessions.pop(key, None)
            return None
        if touch:
            session[1] = now
        return user

    def remaining(self, token: str | None) -> float:
        """Seconds until this session ends if nothing uses it; 0 if it has."""
        session = self._sessions.get(_key(token)) if token else None
        return max(0.0, session[1] + self.lifetime - self.clock()) if session else 0.0

    def valid(self, token: str | None, touch: bool = True) -> bool:
        return self.user(token, touch) is not None

    def close_session(self, token: str | None) -> None:
        if token:
            self._sessions.pop(_key(token), None)

    def cookie(self, token: str) -> str:
        return f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={int(self.lifetime)}"

    @staticmethod
    def clear_cookie() -> str:
        return f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"


class Switches:
    """The admin's live switches, kept across restarts. styri.yaml must allow control at all."""

    def __init__(self, path: str | None):
        self.file = Path(path) if path else None
        self.control, self.anonymous_view = True, True
        if self.file and self.file.is_file():
            saved = json.loads(self.file.read_text(encoding="utf-8"))
            self.control = bool(saved.get("control", True))
            self.anonymous_view = bool(saved.get("anonymous_view", True))

    def save(self) -> None:
        if self.file:
            write_private(self.file, json.dumps({"control": self.control, "anonymous_view": self.anonymous_view}) + "\n")


def token_from(cookie_header: str | None) -> str | None:
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE and value:
            return value
    return None
