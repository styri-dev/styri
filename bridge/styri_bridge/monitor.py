"""What the operator sees: topic rates and ages, robot health, activity.

No ROS imports. The ROS node (or the fake robot) feeds it messages; the
mapping (mapping.py) says which topics and fields become which tiles. The
server asks for a snapshot once a second and state changes go to the
activity log as they happen.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .mapping import RobotMap, Rule, Value, convert, diag_lookup, extract, suggest
from .mapping import from_env as mapping_from_env

# Topics every ROS 2 graph has; they say nothing about the robot.
INFRA_TOPICS = {"/rosout", "/parameter_events"}

RATE_WINDOW = 5.0  # seconds of history used for the Hz figure
NO_ROBOT_GRACE = 30.0  # seconds before "no robot topics" is logged
MISSING_GRACE = 6.0  # seconds of discovery before a mapped topic counts as missing


class Activity(Protocol):
    def add(self, kind: str, msg: str, source: str) -> None: ...


@dataclass
class TopicState:
    name: str
    type: str
    stamps: deque = field(default_factory=lambda: deque(maxlen=500))
    last: float | None = None
    count: int = 0
    raw: object = None  # last message (bytes from ROS, or a dict from the fake)
    supported: bool = True  # False when the message type isn't installed
    stale_since: float | None = None

    def rate(self, now: float) -> float:
        while self.stamps and now - self.stamps[0] > RATE_WINDOW:
            self.stamps.popleft()
        if len(self.stamps) < 2:
            return 0.0
        span = now - self.stamps[0]
        return (len(self.stamps) - 1) / span if span > 0 else 0.0

    def active(self) -> bool:
        """Has published steadily enough that silence means something."""
        return self.count >= 3


@dataclass
class Reading:
    value: Any
    at: float | None
    source: str


def _side(v: float, warn: float | None, fault: float | None, prev: str, hyst: float, low_is_bad: bool) -> str:
    """Level for one bound direction, with hysteresis so it doesn't flap."""
    sign = -1 if low_is_bad else 1
    x = sign * v
    if fault is not None and x >= sign * fault:
        return "fault"
    if warn is not None and x >= sign * warn:
        return "warn"
    # Hysteresis: stay in warn until clearly back to normal.
    edge = warn if warn is not None else fault
    if prev != "ok" and edge is not None and x >= sign * edge - hyst:
        return "warn" if warn is not None else "fault"
    return "ok"


def judge(value: Any, kind: str, rule: Rule, prev: str) -> tuple[str, str | None]:
    """(level, direction) for a value under its rule; direction is high, low or None."""
    if value is None or not rule.judged():
        return "ok", None
    if kind == "number":
        hi = _side(value, rule.warn_above, rule.fault_above, prev, rule.hysteresis, low_is_bad=False)
        lo = _side(value, rule.warn_below, rule.fault_below, prev, rule.hysteresis, low_is_bad=True)
        rank = {"ok": 0, "warn": 1, "fault": 2}
        if hi != "ok" and rank[hi] >= rank[lo]:
            return hi, "high"
        return (lo, "low") if lo != "ok" else ("ok", None)

    def hit(values):
        if kind == "bool":
            return value in values
        return str(value).strip().lower() in {str(x).strip().lower() for x in values}
    if hit(rule.fault):
        return "fault", None
    if hit(rule.warn):
        return "warn", None
    return "ok", None  # unlisted values are shown as they are


def _num(v: float, unit: str) -> str:
    text = f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}"
    return f"{text} {unit}".strip()


def _level_int(level: Any) -> int:
    if isinstance(level, (bytes, bytearray)):
        return int.from_bytes(level, "little")
    return int(level)


class Monitor:
    def __init__(self, activity: Activity, robot: RobotMap | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.activity = activity
        self.robot = robot or mapping_from_env()
        self.clock = clock
        self.started = clock()
        self._lock = threading.Lock()
        self.topics: dict[str, TopicState] = {}
        self.values = {v.key: v for v in self.robot.values}
        self.readings: dict[str, Reading] = {v.key: Reading(None, None, v.topic or "host") for v in self.robot.values}
        self.errors: dict[str, str] = {}  # value key -> why the last message couldn't be read
        self.host_cpu = Reading(None, None, "host")
        self.host_load: float | None = None  # % of all cores, 1-minute average
        self.diag: dict[str, tuple[int, str]] = {}  # status name -> (level, message)
        self.diag_at: float | None = None
        self._by_topic: dict[str, list[Value]] = {}
        for v in self.robot.values:
            if v.topic:
                self._by_topic.setdefault(v.topic, []).append(v)
        # Remembered levels, for transitions.
        self._levels: dict[str, str] = {k: "ok" for k in self.values}
        self._diag_levels: dict[str, int] = {}
        self._overall = None
        self._graph_announced = False
        self._no_robot_logged = False
        self._missing_logged: set[str] = set()
        self._error_logged: set[str] = set()

    def mapped_topics(self) -> set[str]:
        """Topics whose messages need decoding (the rest are only counted)."""
        return self.robot.topics()

    # ---- inputs (any thread) -------------------------------------------

    def discovered(self, names_and_types: list[tuple[str, str]], supported: Callable[[str], bool]) -> list[str]:
        """Record the current graph. Returns topics that are new."""
        new = []
        with self._lock:
            for name, type_ in names_and_types:
                if name not in self.topics:
                    self.topics[name] = TopicState(name, type_, supported=supported(type_))
                    new.append(name)
        return new

    def message(self, name: str, raw: object, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        with self._lock:
            t = self.topics.get(name)
            if t is None:
                return
            t.stamps.append(now)
            t.last = now
            t.count += 1
            t.raw = raw

    def mapped(self, name: str, msg: Any, now: float | None = None) -> None:
        """A decoded message (a ROS message, or a dict from the fake robot) on a mapped topic."""
        now = self.clock() if now is None else now
        statuses = None
        if name == self.robot.diagnostics_topic:
            try:
                statuses = [(str(extract(s, "name")), _level_int(extract(s, "level")), str(extract(s, "message")))
                            for s in extract(msg, "status")]
            except (LookupError, TypeError, ValueError):
                statuses = None
        with self._lock:
            for v in self._by_topic.get(name, ()):
                try:
                    raw = diag_lookup(msg, v.diag_status, v.diag_key) if v.diag_status is not None \
                        else extract(msg, v.field)
                    value = convert(raw, v.kind)
                    if v.kind == "number" and value is not None:
                        value *= v.scale
                except (LookupError, TypeError, ValueError) as exc:
                    self.errors[v.key] = str(exc)
                    continue
                self.errors.pop(v.key, None)
                self.readings[v.key] = Reading(value, now, name)
            if statuses is not None:
                for status_name, level, text in statuses:
                    self.diag[status_name] = (level, text)
                self.diag_at = now

    def host_vitals(self, cpu_temperature: float | None, load_pct: float | None = None,
                    now: float | None = None) -> None:
        now = self.clock() if now is None else now
        with self._lock:
            self.host_cpu = Reading(cpu_temperature, now, "host")
            self.host_load = load_pct

    # ---- derived state ------------------------------------------------------

    @staticmethod
    def _stale(r: Reading, now: float, after: float) -> bool:
        return r.at is not None and now - r.at > after

    def _reading(self, v: Value, now: float) -> tuple[Reading, str]:
        """The reading behind a tile, and the label to show with it."""
        if v.topic is None:  # cpu_temperature: {topic: host}
            return self.host_cpu, "Styri host CPU"
        r = self.readings[v.key]
        # Only when the file asks for it (host_fallback: true), and labelled as such.
        if v.key == "cpu_temp" and self.robot.host_fallback and self.host_cpu.value is not None \
                and (r.value is None or self._stale(r, now, v.stale_after)):
            return self.host_cpu, "Styri host CPU"
        return r, v.label

    def robot_found(self) -> bool:
        return any(t in self.topics for t in self.mapped_topics())

    def evaluate(self, now: float | None = None) -> dict:
        """Snapshot for the UI, logging any state changes on the way."""
        now = self.clock() if now is None else now
        with self._lock:
            snap = self._evaluate(now)
        return snap

    def _evaluate(self, now: float) -> dict:
        tiles: dict[str, dict] = {}
        reasons: list[tuple[str, str]] = []
        robot_readings: list[tuple[Reading, float]] = []
        for v in self.robot.values:
            r, label = self._reading(v, now)
            stale = self._stale(r, now, v.stale_after)
            level, direction = ("ok", None) if stale else judge(r.value, v.kind, v.rule, self._levels[v.key])
            self._transition(v, level, direction, r.source, r.value)
            self._levels[v.key] = level
            if r.source != "host" and r.at is not None:
                robot_readings.append((r, v.stale_after))
            if level != "ok":
                reasons.append((level, self._reason(v, r.value, level, direction)))
            tiles[v.key] = {"value": r.value, "age": None if r.at is None else round(now - r.at, 1),
                            "source": r.source, "level": level, "stale": stale, "label": label,
                            "unit": v.unit, "kind": v.kind, "mapped": True}

        # Diagnostics: 0 OK, 1 WARN, 2 ERROR, 3 STALE.
        diag_stale = self.diag_at is not None and now - self.diag_at > self.robot.stale_after
        cpu = self.values.get("cpu_temp")
        cpu_entry = cpu.diag_status.lower() if cpu and cpu.diag_status else None
        cpu_hot = tiles.get("cpu_temp", {}).get("level", "ok") != "ok"
        for name, (level, message) in sorted(self.diag.items()):
            prev = self._diag_levels.get(name, 0)
            # The CPU tile already speaks for a hot CPU; don't say it twice.
            if cpu_hot and cpu_entry and cpu_entry in name.lower():
                self._diag_levels[name] = level
                continue
            if level in (1, 2) and level > prev:
                self.activity.add("warning", f"{name}: {message or ('error' if level == 2 else 'warning')}",
                                  self.robot.diagnostics_topic)
            elif level == 0 and prev in (1, 2):
                self.activity.add("state", f"{name} back to OK", self.robot.diagnostics_topic)
            self._diag_levels[name] = level
            if not diag_stale and level in (1, 2):
                reasons.append(("fault" if level == 2 else "warn", f"{name} reports {message or 'a problem'}."))

        all_stale = bool(robot_readings) and all(self._stale(r, now, after) for r, after in robot_readings)
        if all_stale:
            last = max(r.at for r, _ in robot_readings)
            overall, line = "unknown", f"No data from the robot for {now - last:.0f} s."
        elif any(level == "fault" for level, _ in reasons):
            overall = "fault"
            line = " ".join(text for level, text in reasons if level == "fault")
        elif reasons:
            overall = "warn"
            line = " ".join(text for _, text in reasons)
        else:
            overall = "ok"
            stale_names = [{"battery": "battery", "cpu_temp": "CPU temp"}.get(k, t["label"])
                           for k, t in tiles.items() if t["stale"] and k != "voltage"]
            line = (f"Robot healthy. One value is stale — see {stale_names[0]}." if len(stale_names) == 1
                    else f"Robot healthy. {len(stale_names)} values are stale." if stale_names
                    else "All systems normal.")

        names = {"ok": "OK", "warn": "WARNING", "fault": "FAULT", "unknown": "NO DATA"}
        if self._overall is not None and overall != self._overall and self.robot_found():
            self.activity.add("state", f"Robot status changed {names[self._overall]} → {names[overall]}", "overview")
        self._overall = overall

        topics = self._topic_rows(now)
        self._graph_events(now, len(topics))
        mappings = self._mapping_rows(now, tiles)

        robot_topics = [t for t in self.topics.values() if t.name not in INFRA_TOPICS and t.last is not None]
        newest = max(robot_topics, key=lambda t: t.last, default=None)
        empty = {"value": None, "age": None, "source": None, "level": "ok", "stale": False, "label": None,
                 "unit": "", "kind": "number", "mapped": False}

        return {
            "robot_found": self.robot_found(),
            "health": {"level": overall, "line": line},
            "battery": tiles.get("battery", empty),
            "voltage": tiles.get("voltage", empty),
            "cpu_temp": tiles.get("cpu_temp", empty),
            "status": tiles.get("status"),
            "fields": [tiles[k] | {"key": k} for k in tiles if k.startswith("field")],
            "mappings": mappings,
            "last_message": {"age": None if newest is None else round(now - newest.last, 2),
                             "topic": None if newest is None else newest.name},
            "topics": topics,
            "seen": sorted(self.topics),
            "host": {"load_pct": self.host_load},
        }

    @staticmethod
    def _reason(v: Value, value: Any, level: str, direction: str | None) -> str:
        if v.key == "battery":
            return f"Battery critical — {value:.0f} %. Dock the robot now." if level == "fault" \
                else f"Battery low — {value:.0f} %. Send to dock soon."
        if v.key == "voltage":
            return f"Battery voltage low — {value:.2f} V, below {v.rule.warn_below:.1f} V."
        if v.key == "cpu_temp":
            return f"CPU temperature high — {value:.1f} °C."
        if v.kind == "number":
            return f"{v.label} {direction or 'out of range'} — {_num(value, v.unit)}."
        shown = ("true" if value else "false") if v.kind == "bool" else value
        return f"{v.label} reports {shown}."

    def _transition(self, v: Value, level: str, direction: str | None, source: str, value: Any) -> None:
        prev = self._levels[v.key]
        if level == prev or level == "ok" or not (prev == "ok" or level == "fault"):
            return
        r = v.rule
        if v.key == "battery":
            msg = f"Battery below {(r.fault_below if level == 'fault' else r.warn_below):.0f} %"
        elif v.key == "voltage":
            msg = f"Voltage below {r.warn_below:.1f} V"
        elif v.key == "cpu_temp":
            msg = f"CPU temperature above {(r.fault_above if level == 'fault' else r.warn_above):.0f} °C"
        elif v.kind == "number":
            bound = {("high", "warn"): r.warn_above, ("high", "fault"): r.fault_above,
                     ("low", "warn"): r.warn_below, ("low", "fault"): r.fault_below}.get((direction, level))
            word = "above" if direction == "high" else "below"
            msg = f"{v.label} {word} {_num(bound, v.unit)}" if bound is not None else f"{v.label} out of range"
        else:
            msg = f"{v.label}: {('true' if value else 'false') if v.kind == 'bool' else value}"
        self.activity.add("warning", msg, source)

    def _mapping_rows(self, now: float, tiles: dict[str, dict]) -> list[dict]:
        """Each mapping and whether it's working, for the banner and the Configuration view."""
        seen = sorted(self.topics)
        entries = [(v.key, v.label, v.topic, v.describe(), v) for v in self.robot.values]
        if self.robot.diagnostics_topic:
            entries.append(("diagnostics", "Diagnostics", self.robot.diagnostics_topic,
                            f"{self.robot.diagnostics_topic} · status levels", None))
        rows = []
        for key, label, topic, where, v in entries:
            row = {"key": key, "label": label, "topic": topic, "where": where, "suggestions": [],
                   "status": "ok", "detail": ""}
            t = self.topics.get(topic) if topic else None
            if topic is None:
                ok = self.host_cpu.value is not None
                row.update(status="ok" if ok else "missing",
                           detail="Reading the Styri machine's own sensor." if ok
                           else "The Styri machine reports no CPU temperature sensor.")
            elif t is None:
                if now - self.started < MISSING_GRACE:
                    row.update(status="waiting", detail="Looking for it on the network…")
                else:
                    row["suggestions"] = suggest(topic, seen)
                    row.update(status="missing", detail="Not on the network.")
                    if topic not in self._missing_logged:
                        self._missing_logged.add(topic)
                        hint = f" Did you mean {row['suggestions'][0]}?" if row["suggestions"] else ""
                        self.activity.add("warning", f"Mapped topic {topic} not found.{hint}", "configuration")
            elif not t.supported:
                row.update(status="error", detail=f"Its type, {t.type}, isn't installed here, so Styri can't read it.")
            elif v is not None and key in self.errors and (tiles[key]["age"] is None or tiles[key]["stale"]):
                row.update(status="error", detail=f"Can't read the value: {self.errors[key]}.")
                if key not in self._error_logged:
                    self._error_logged.add(key)
                    self.activity.add("warning", f"{label}: can't read {where} — {self.errors[key]}", "configuration")
            elif v is None:
                stale = t.last is not None and now - t.last > self.robot.stale_after
                row.update(status="waiting" if t.last is None else "stale" if stale else "ok",
                           detail="On the network, no messages yet." if t.last is None else "")
            elif tiles[key]["age"] is None:
                row.update(status="waiting", detail="On the network, no messages yet.")
            elif tiles[key]["stale"]:
                row.update(status="stale", detail=f"No update for {tiles[key]['age']:.0f} s "
                                                  f"(stale after {v.stale_after:g} s).")
            if row["status"] == "ok":
                self._missing_logged.discard(topic)
            if row["status"] != "error":
                self._error_logged.discard(key)
            if v is not None:
                row.update(type=t.type if t else None, value=tiles[key]["value"], unit=v.unit, kind=v.kind,
                           stale_after=v.stale_after)
            rows.append(row)
        return rows

    def _topic_rows(self, now: float) -> list[dict]:
        rows = []
        for t in sorted(self.topics.values(), key=lambda t: t.name):
            age = None if t.last is None else now - t.last
            stale = t.active() and age is not None and age > self.robot.stale_after
            if stale and t.stale_since is None:
                t.stale_since = t.last
                self.activity.add("warning", f"{t.name} stopped publishing", t.name)
            elif not stale and t.stale_since is not None:
                self.activity.add("state", f"{t.name} recovered after {now - t.stale_since:.0f} s", t.name)
                t.stale_since = None
            rows.append({"name": t.name, "type": t.type, "hz": round(t.rate(now), 1),
                         "age": None if age is None else round(age, 2), "stale": stale,
                         "supported": t.supported})
        return rows

    def _graph_events(self, now: float, count: int) -> None:
        if not self._graph_announced and count and self.robot_found():
            self._graph_announced = True
            self._no_robot_logged = False
            self.activity.add("connection", f"Bridge sees the robot · {count} topics", "styri-bridge")
        if not self.robot_found() and not self._no_robot_logged and now - self.started > NO_ROBOT_GRACE:
            self._no_robot_logged = True
            self.activity.add("warning", f"No expected robot topics after {NO_ROBOT_GRACE:.0f} s", "styri-bridge")

    def latest(self, name: str) -> tuple[TopicState | None, object]:
        with self._lock:
            t = self.topics.get(name)
            return t, (t.raw if t else None)
