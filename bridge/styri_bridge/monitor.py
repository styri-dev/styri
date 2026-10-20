"""What the operator sees: topic rates and ages, robot health, activity.

No ROS imports. The ROS node (or the fake robot) feeds it messages; the
server asks it for a snapshot once a second and it reports state changes
to the activity log as they happen.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Protocol

# Topics every ROS 2 graph has; they say nothing about the robot.
INFRA_TOPICS = {"/rosout", "/parameter_events"}

RATE_WINDOW = 5.0  # seconds of history used for the Hz figure
VOLTAGE_HYSTERESIS = 0.2  # V above STYRI_MIN_VOLTAGE before a low-voltage warning clears
NO_ROBOT_GRACE = 30.0  # seconds before "no robot topics" is logged


class Activity(Protocol):
    def add(self, kind: str, msg: str, source: str) -> None: ...


@dataclass
class Thresholds:
    battery_warn: float = 25.0  # %
    battery_fault: float = 10.0
    cpu_warn: float = 75.0  # °C
    cpu_fault: float = 85.0
    hysteresis: float = 2.0  # must recover this far past a limit to clear


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
    value: float | None
    at: float | None
    source: str


def _level(value: float | None, warn: float, fault: float, prev: str, hyst: float, low_is_bad: bool) -> str:
    if value is None:
        return "ok"
    v = -value if low_is_bad else value
    w, f = (-warn, -fault) if low_is_bad else (warn, fault)
    if v >= f:
        return "fault"
    if v >= w:
        return "warn"
    # Hysteresis: stay in warn until clearly back to normal.
    if prev != "ok" and v >= w - hyst:
        return "warn"
    return "ok"


class Monitor:
    def __init__(self, activity: Activity, battery_topic: str, diagnostics_topic: str,
                 stale_after: float = 5.0, thresholds: Thresholds | None = None,
                 min_voltage: float | None = None, clock: Callable[[], float] = time.monotonic):
        self.activity = activity
        self.battery_topic = battery_topic
        self.diagnostics_topic = diagnostics_topic
        self.stale_after = stale_after
        self.th = thresholds or Thresholds()
        # Optional: warn when the pack voltage drops below this, whatever the
        # reported charge says (a sagging pack can still claim plenty left).
        self.min_voltage = min_voltage
        self.clock = clock
        self.started = clock()
        self._lock = threading.Lock()
        self.topics: dict[str, TopicState] = {}
        self.battery = Reading(None, None, battery_topic)
        self.voltage = Reading(None, None, battery_topic)
        self.cpu = Reading(None, None, "host")
        self.host_cpu = Reading(None, None, "host")
        self.host_load: float | None = None  # % of all cores, 1-minute average
        self.diag: dict[str, tuple[int, str]] = {}  # status name -> (level, message)
        self.diag_at: float | None = None
        # Remembered levels, for transitions.
        self._levels = {"battery": "ok", "cpu": "ok", "voltage": "ok"}
        self._diag_levels: dict[str, int] = {}
        self._overall = None
        self._graph_announced = False
        self._no_robot_logged = False

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

    def battery_state(self, percentage: float | None, voltage: float | None, now: float | None = None) -> None:
        """percentage in 0..100 (already converted), None when unknown."""
        now = self.clock() if now is None else now
        with self._lock:
            self.battery = Reading(percentage, now, self.battery_topic)
            self.voltage = Reading(voltage, now, self.battery_topic)

    def diagnostics(self, statuses: list[tuple[str, int, str, dict[str, str]]], now: float | None = None) -> None:
        """(name, level, message, values) per DiagnosticStatus."""
        now = self.clock() if now is None else now
        with self._lock:
            for name, level, message, values in statuses:
                self.diag[name] = (level, message)
                if "cpu" in name.lower():
                    for key, value in values.items():
                        if "temp" in key.lower():
                            try:
                                self.cpu = Reading(float(value), now, self.diagnostics_topic)
                            except ValueError:
                                pass
            self.diag_at = now

    def host_vitals(self, cpu_temperature: float | None, load_pct: float | None = None,
                    now: float | None = None) -> None:
        now = self.clock() if now is None else now
        with self._lock:
            self.host_cpu = Reading(cpu_temperature, now, "host")
            self.host_load = load_pct

    # ---- derived state ------------------------------------------------------

    def _cpu_reading(self, now: float) -> Reading:
        # Prefer the robot's own /diagnostics figure while it is fresh.
        if self.cpu.value is not None and self.cpu.at is not None and now - self.cpu.at <= self.stale_after:
            return self.cpu
        if self.host_cpu.value is not None:
            return self.host_cpu
        return self.cpu

    def _stale(self, r: Reading, now: float) -> bool:
        return r.at is not None and now - r.at > self.stale_after

    def robot_found(self) -> bool:
        return self.battery_topic in self.topics or self.diagnostics_topic in self.topics

    def evaluate(self, now: float | None = None) -> dict:
        """Snapshot for the UI, logging any state changes on the way."""
        now = self.clock() if now is None else now
        with self._lock:
            snap = self._evaluate(now)
        return snap

    def _evaluate(self, now: float) -> dict:
        th = self.th
        cpu = self._cpu_reading(now)
        bat_stale, cpu_stale = self._stale(self.battery, now), self._stale(cpu, now)

        bat_level = "ok" if bat_stale else _level(self.battery.value, th.battery_warn, th.battery_fault,
                                                  self._levels["battery"], th.hysteresis, low_is_bad=True)
        cpu_level = "ok" if cpu_stale else _level(cpu.value, th.cpu_warn, th.cpu_fault,
                                                  self._levels["cpu"], th.hysteresis, low_is_bad=False)
        self._transition("battery", bat_level,
                         {"warn": f"Battery below {th.battery_warn:.0f} %", "fault": f"Battery below {th.battery_fault:.0f} %"},
                         self.battery_topic)
        volt_level = "ok"
        v = self.voltage.value
        if self.min_voltage is not None and v is not None and not bat_stale:
            recovering = self._levels["voltage"] != "ok" and v < self.min_voltage + VOLTAGE_HYSTERESIS
            volt_level = "warn" if v < self.min_voltage or recovering else "ok"
        self._transition("voltage", volt_level, {"warn": f"Voltage below {self.min_voltage or 0:.1f} V"},
                         self.battery_topic)
        self._transition("cpu", cpu_level,
                         {"warn": f"CPU temperature above {th.cpu_warn:.0f} °C", "fault": f"CPU temperature above {th.cpu_fault:.0f} °C"},
                         cpu.source)

        # Diagnostics: 0 OK, 1 WARN, 2 ERROR, 3 STALE.
        diag_stale = self.diag_at is not None and now - self.diag_at > self.stale_after
        diag_reasons = []
        for name, (level, message) in sorted(self.diag.items()):
            prev = self._diag_levels.get(name, 0)
            # The CPU tile already speaks for a hot CPU; don't say it twice.
            if cpu_level != "ok" and "cpu" in name.lower():
                self._diag_levels[name] = level
                continue
            if level in (1, 2) and level > prev:
                self.activity.add("warning", f"{name}: {message or ('error' if level == 2 else 'warning')}",
                                  self.diagnostics_topic)
            elif level == 0 and prev in (1, 2):
                self.activity.add("state", f"{name} back to OK", self.diagnostics_topic)
            self._diag_levels[name] = level
            if not diag_stale and level in (1, 2):
                diag_reasons.append(("fault" if level == 2 else "warn", f"{name} reports {message or 'a problem'}."))

        reasons = []
        if bat_level != "ok":
            pct = self.battery.value or 0
            reasons.append((bat_level, f"Battery critical — {pct:.0f} %. Dock the robot now." if bat_level == "fault"
                            else f"Battery low — {pct:.0f} %. Send to dock soon."))
        if volt_level != "ok":
            reasons.append((volt_level, f"Battery voltage low — {v:.2f} V, below {self.min_voltage:.1f} V."))
        if cpu_level != "ok":
            reasons.append((cpu_level, f"CPU temperature high — {cpu.value:.1f} °C."))
        reasons += diag_reasons

        tracked = [r for r in (self.battery, cpu) if r.at is not None]
        all_stale = bool(tracked) and all(self._stale(r, now) for r in tracked)
        if all_stale:
            last = max(r.at for r in tracked)
            overall, line = "unknown", f"No data from the robot for {now - last:.0f} s."
        elif any(level == "fault" for level, _ in reasons):
            overall = "fault"
            line = " ".join(text for level, text in reasons if level == "fault")
        elif reasons:
            overall = "warn"
            line = " ".join(text for _, text in reasons)
        else:
            overall = "ok"
            stale_names = [n for n, s in (("battery", bat_stale), ("CPU temp", cpu_stale)) if s]
            line = (f"Robot healthy. One value is stale — see {stale_names[0]}." if len(stale_names) == 1
                    else "All systems normal.")

        names = {"ok": "OK", "warn": "WARNING", "fault": "FAULT", "unknown": "NO DATA"}
        if self._overall is not None and overall != self._overall and self.robot_found():
            self.activity.add("state", f"Robot status changed {names[self._overall]} → {names[overall]}", "overview")
        self._overall = overall

        topics = self._topic_rows(now)
        self._graph_events(now, len(topics))

        robot_topics = [t for t in self.topics.values() if t.name not in INFRA_TOPICS and t.last is not None]
        newest = max(robot_topics, key=lambda t: t.last, default=None)

        return {
            "robot_found": self.robot_found(),
            "health": {"level": overall, "line": line},
            "battery": self._tile(self.battery, now, bat_level, bat_stale),
            "voltage": self._tile(self.voltage, now, volt_level, bat_stale),
            "cpu_temp": self._tile(cpu, now, cpu_level, cpu_stale),
            "last_message": {"age": None if newest is None else round(now - newest.last, 2),
                             "topic": None if newest is None else newest.name},
            "topics": topics,
            "seen": sorted(self.topics),
            "host": {"load_pct": self.host_load},
        }

    @staticmethod
    def _tile(r: Reading, now: float, level: str, stale: bool) -> dict:
        return {"value": r.value, "age": None if r.at is None else round(now - r.at, 1),
                "source": r.source, "level": level, "stale": stale}

    def _transition(self, key: str, level: str, messages: dict[str, str], source: str) -> None:
        prev = self._levels[key]
        if level != prev and level != "ok" and (prev == "ok" or level == "fault"):
            self.activity.add("warning", messages[level], source)
        self._levels[key] = level

    def _topic_rows(self, now: float) -> list[dict]:
        rows = []
        for t in sorted(self.topics.values(), key=lambda t: t.name):
            age = None if t.last is None else now - t.last
            stale = t.active() and age is not None and age > self.stale_after
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
