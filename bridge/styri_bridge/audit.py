"""Local SQLite log: the activity a browser sees, plus a few internal records."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    kind    TEXT    NOT NULL,
    client  TEXT,
    user    TEXT,
    action  TEXT,
    detail  TEXT
);
"""


class AuditLog:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(_SCHEMA)
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(events)")}
        if "user" not in columns:  # databases from v0.1.0
            self._db.execute("ALTER TABLE events ADD COLUMN user TEXT")

    def record(self, kind: str, *, client: str | None = None, user: str | None = None,
               action: str | None = None, **detail) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO events (ts, kind, client, user, action, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), kind, client, user, action, json.dumps(detail) if detail else None),
            )

    def rows(self) -> list[tuple]:
        with self._lock:
            return self._db.execute(
                "SELECT id, ts, kind, client, user, action, detail FROM events ORDER BY id"
            ).fetchall()

    def close(self) -> None:
        with self._lock:
            self._db.close()


ACTIVITY_KINDS = ("connection", "state", "warning")


class Activity:
    """The operator-facing activity log: connections, state changes, warnings.

    Stored in the same SQLite file as the audit trail and pushed live to
    every connected browser.
    """

    def __init__(self, audit: AuditLog, publish=None):
        self.audit = audit
        self.publish = publish  # set by the server: callable(dict), thread-safe

    def add(self, kind: str, msg: str, source: str) -> None:
        assert kind in ACTIVITY_KINDS, kind
        ts = time.time()
        with self.audit._lock:
            cur = self.audit._db.execute(
                "INSERT INTO events (ts, kind, client, user, action, detail) VALUES (?, ?, NULL, NULL, NULL, ?)",
                (ts, kind, json.dumps({"msg": msg, "source": source})),
            )
            event_id = cur.lastrowid
        if self.publish:
            self.publish({"type": "event", "event": {"id": event_id, "ts": ts, "kind": kind, "msg": msg, "source": source}})

    def recent(self, limit: int = 2000) -> list[dict]:
        with self.audit._lock:
            rows = self.audit._db.execute(
                f"SELECT id, ts, kind, detail FROM events WHERE kind IN ({','.join('?' * len(ACTIVITY_KINDS))}) "
                "ORDER BY id DESC LIMIT ?", (*ACTIVITY_KINDS, limit)).fetchall()
        events = []
        for id_, ts, kind, detail in rows:
            d = json.loads(detail) if detail else {}
            events.append({"id": id_, "ts": ts, "kind": kind, "msg": d.get("msg", ""), "source": d.get("source", "")})
        return events
