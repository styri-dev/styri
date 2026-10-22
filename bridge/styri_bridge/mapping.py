"""Topic mapping: which topics and fields feed the panel. No ROS imports.

A robot is described by one YAML file (styri.yaml), loaded at start from
STYRI_CONFIG or /etc/styri/styri.yaml. Without a file, the STYRI_* environment
variables describe a sensor_msgs/BatteryState robot, as before.

    robot:
      name: amr-01
      namespace: /robot1          # prefix for relative topic names
    battery:
      topic: battery_state
      percentage: percentage      # field path, e.g. data or status.level[0]
      percentage_scale: 100       # multiply to get %; 1 if it already sends 0-100
      voltage: voltage
      warn_below: 25
      fault_below: 10
      min_voltage: 23.0           # optional
    status:                       # optional: the robot's own status
      topic: robot_status
      field: data
      warn: [DEGRADED]
      fault: [ERROR, ESTOP]
    cpu_temperature:
      topic: /diagnostics         # a DiagnosticArray: pick an entry and key ...
      status_name: cpu
      key: temp
      # field: temperature        # ... or any topic, by field path
      warn_above: 75
      fault_above: 85
      host_fallback: false        # true: use the Styri machine's own sensor
    fields:                       # up to 5 custom tiles
      - label: Motor current
        topic: motor/current
        field: data
        unit: A
        warn_above: 12

A file may instead hold `robots:`, a list of robot entries in the same
shape, with any top-level sections as shared defaults. Styri Core shows the
first robot; Styri Pilot shows up to five.
"""

from __future__ import annotations

import difflib
import math
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = "/etc/styri/styri.yaml"
MAX_FIELDS = 5
CUSTOM_STALE_AFTER = 3.0
SECTIONS = {"robot", "battery", "status", "cpu_temperature", "diagnostics", "fields", "stale_after"}
KINDS = {"number", "text", "bool"}


class ConfigError(ValueError):
    """The file can't be used as written. Messages name the offending key."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Rule:
    """When a value means WARNING or FAULT. Unset bounds are never checked."""
    warn_above: float | None = None
    fault_above: float | None = None
    warn_below: float | None = None
    fault_below: float | None = None
    warn: tuple = ()   # values (text or booleans) that mean WARNING
    fault: tuple = ()  # values that mean FAULT
    hysteresis: float = 0.0  # must recover this far past a bound to clear

    def judged(self) -> bool:
        return any(v is not None for v in (self.warn_above, self.fault_above, self.warn_below, self.fault_below)) \
            or bool(self.warn or self.fault)


@dataclass(frozen=True)
class Value:
    """One value on the panel: where it comes from and how it's judged."""
    key: str                 # battery, voltage, cpu_temp, status, field1..field5
    label: str
    topic: str | None        # resolved (namespaced); None for the host sensor
    field: str = ""          # field path in the message
    unit: str = ""
    kind: str = "number"     # number, text or bool
    scale: float = 1.0
    rule: Rule = Rule()
    stale_after: float = 5.0
    # For a diagnostic_msgs/DiagnosticArray: match an entry and a key by name
    # (case-insensitive substrings) instead of a field path.
    diag_status: str | None = None
    diag_key: str | None = None

    def describe(self) -> str:
        if self.topic is None:
            return "this machine's own sensor"
        if self.diag_status is not None:
            return f"{self.topic} · entry “{self.diag_status}”, key “{self.diag_key}”"
        return f"{self.topic} · {self.field}" if self.field else self.topic


@dataclass(frozen=True)
class RobotMap:
    name: str
    namespace: str = ""
    domain_id: int | None = None
    values: tuple[Value, ...] = ()
    diagnostics_topic: str | None = "/diagnostics"
    host_fallback: bool = False
    stale_after: float = 5.0

    def value(self, key: str) -> Value | None:
        return next((v for v in self.values if v.key == key), None)

    def topics(self) -> set[str]:
        out = {v.topic for v in self.values if v.topic}
        if self.diagnostics_topic:
            out.add(self.diagnostics_topic)
        return out


@dataclass(frozen=True)
class Loaded:
    robots: tuple[RobotMap, ...]
    source: str            # the file path, or "environment"
    notes: tuple[str, ...] = ()
    error: str | None = None  # set when the file couldn't be used (env defaults apply)


# ---- field paths --------------------------------------------------------

_PART = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)((?:\[\d+\])*)")


def parse_path(path: str) -> list[str | int]:
    """'status.values[0].value' -> ['status', 'values', 0, 'value']."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("is empty")
    parts: list[str | int] = []
    for chunk in path.strip().split("."):
        m = _PART.fullmatch(chunk)
        if not m:
            raise ValueError(f"“{path}” is not a field path (use names, dots and [index])")
        parts.append(m.group(1))
        parts += [int(i) for i in re.findall(r"\[(\d+)\]", m.group(2))]
    return parts


def _child(obj: Any, part: str | int) -> Any:
    if isinstance(part, int):
        try:
            return obj[part]
        except (IndexError, KeyError, TypeError):
            raise LookupError(f"no item [{part}]") from None
    if isinstance(obj, dict):
        if part in obj:
            return obj[part]
    elif hasattr(obj, part) and not part.startswith("_"):
        return getattr(obj, part)
    raise LookupError(f"no field “{part}”{_fields_hint(obj)}")


def _fields_hint(obj: Any) -> str:
    names = list(obj) if isinstance(obj, dict) else \
        [s.lstrip("_") for s in getattr(obj, "__slots__", ()) if s.startswith("_") and s != "_check_fields"]
    return f" (it has: {', '.join(names[:12])})" if names else ""


def extract(msg: Any, path: str) -> Any:
    obj = msg
    for part in parse_path(path):
        obj = _child(obj, part)
    return obj


def convert(raw: Any, kind: str) -> Any:
    """A message value as a panel value. None means unknown (NaN, missing)."""
    if isinstance(raw, (bytes, bytearray)) and len(raw) == 1:
        raw = raw[0]  # rclpy hands uint8/byte fields over as bytes
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
        raise TypeError(f"is {type(raw).__name__}, not a boolean")
    if kind == "text":
        return raw if isinstance(raw, str) else str(raw)
    if isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, (int, float)):
        return float(raw) if math.isfinite(raw) else None
    if isinstance(raw, str):
        try:
            v = float(raw)
        except ValueError:
            raise TypeError(f"is text (“{raw[:40]}”), not a number; use kind: text") from None
        return v if math.isfinite(v) else None
    raise TypeError(f"is a {type(raw).__name__}, not a number; point the field path at a single value")


def diag_lookup(msg: Any, status_name: str, key: str) -> str:
    """The value of `key` in the DiagnosticStatus whose name contains `status_name`."""
    statuses = _child(msg, "status")
    for s in statuses:
        if status_name.lower() in str(_child(s, "name")).lower():
            for kv in _child(s, "values"):
                if key.lower() in str(_child(kv, "key")).lower():
                    return _child(kv, "value")
            raise LookupError(f"entry “{_child(s, 'name')}” has no key like “{key}”")
    raise LookupError(f"no diagnostics entry like “{status_name}”")


# ---- topics -------------------------------------------------------------

def resolve(topic: str, namespace: str) -> str:
    """Relative names get the robot's namespace; absolute names are kept."""
    topic = topic.strip()
    if topic.startswith("/"):
        return topic
    ns = "/" + namespace.strip("/") if namespace.strip("/") else ""
    return f"{ns}/{topic}"


def suggest(topic: str, seen: list[str], n: int = 3) -> list[str]:
    """Close matches among the topics on the network, best first."""
    base = topic.rsplit("/", 1)[-1]
    same_name = [t for t in seen if t != topic and t.rsplit("/", 1)[-1] == base]
    close = difflib.get_close_matches(topic, [t for t in seen if t != topic], n=n, cutoff=0.75)
    close_base = [t for t in seen if t != topic and
                  difflib.SequenceMatcher(None, base, t.rsplit("/", 1)[-1]).ratio() >= 0.85]
    tail = lambda t: t.rsplit("/", 1)[-1]  # noqa: E731
    prefix = [t for t in seen if t != topic and len(base) >= 4 and len(tail(t)) >= 4
              and (tail(t).startswith(base) or base.startswith(tail(t)))]
    out = []
    for t in same_name + close + prefix + close_base:
        if t not in out:
            out.append(t)
    return out[:n]


# ---- loading ------------------------------------------------------------

class _Reader:
    """Typed access to one YAML mapping, collecting every problem at once."""

    def __init__(self, data: Any, where: str, problems: list[str], known: set[str]):
        self.where, self.problems = where, problems
        self.prefix = f"{where}." if where else ""
        if data is None:
            data = {}
        if not isinstance(data, dict):
            problems.append(f"{where or 'the file'}: expected a mapping (key: value lines)")
            data = {}
        for k in data:
            if k not in known:
                close = difflib.get_close_matches(str(k), sorted(known), n=1)
                problems.append(f"{self.prefix}{k}: unknown key" + (f" (did you mean “{close[0]}”?)" if close else ""))
        self.data = data

    def has(self, key: str) -> bool:
        return key in self.data and self.data[key] is not None

    def str(self, key: str, default: str | None = None) -> str | None:
        v = self.data.get(key, default)
        if v is None:
            return default
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        if not isinstance(v, str):
            self.problems.append(f"{self.prefix}{key}: expected text")
            return default
        return v

    def num(self, key: str, default: float | None = None, positive: bool = False) -> float | None:
        v = self.data.get(key, default)
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.problems.append(f"{self.prefix}{key}: expected a number")
            return default
        if positive and v <= 0:
            self.problems.append(f"{self.prefix}{key}: must be above 0")
            return default
        return float(v)

    def bool(self, key: str, default: bool = False) -> bool:
        v = self.data.get(key, default)
        if not isinstance(v, bool):
            self.problems.append(f"{self.prefix}{key}: expected true or false")
            return default
        return v

    def values(self, key: str) -> tuple:
        v = self.data.get(key)
        if v is None:
            return ()
        if not isinstance(v, list):
            v = [v]
        out = []
        for item in v:
            if isinstance(item, (str, bool)) or (isinstance(item, (int, float))):
                out.append(item)
            else:
                self.problems.append(f"{self.prefix}{key}: list text, numbers or true/false")
        return tuple(out)

    def path(self, key: str, default: str | None = None) -> str | None:
        v = self.str(key, default)
        if v is None:
            return None
        try:
            parse_path(v)
        except ValueError as exc:
            self.problems.append(f"{self.prefix}{key}: {exc}")
            return default
        return v

    def topic(self, key: str, default: str | None = None) -> str | None:
        v = self.str(key, default)
        if v is not None and not re.fullmatch(r"/?[A-Za-z~{][A-Za-z0-9_/{}~]*", v.strip()):
            self.problems.append(f"{self.prefix}{key}: “{v}” is not a ROS topic name")
            return default
        return v


THRESHOLDS = {"warn_above", "fault_above", "warn_below", "fault_below", "hysteresis"}


def _rule(r: _Reader, kind: str, defaults: Rule = Rule()) -> Rule:
    rule = Rule(
        warn_above=r.num("warn_above", defaults.warn_above), fault_above=r.num("fault_above", defaults.fault_above),
        warn_below=r.num("warn_below", defaults.warn_below), fault_below=r.num("fault_below", defaults.fault_below),
        warn=r.values("warn") or defaults.warn, fault=r.values("fault") or defaults.fault,
        hysteresis=r.num("hysteresis", defaults.hysteresis) or 0.0)
    numeric = any(v is not None for v in (rule.warn_above, rule.fault_above, rule.warn_below, rule.fault_below))
    if kind == "number" and (rule.warn or rule.fault):
        r.problems.append(f"{r.where}: warn/fault value lists are for text and true/false fields; "
                          "use warn_above/warn_below for numbers")
    if kind in ("text", "bool") and numeric:
        r.problems.append(f"{r.where}: warn_above/warn_below are for numbers; use warn: [...] for {kind} fields")
    if kind == "bool" and any(not isinstance(v, bool) for v in rule.warn + rule.fault):
        r.problems.append(f"{r.where}: list true or false for a true/false field")
    if kind == "text" and any(isinstance(v, bool) for v in rule.warn + rule.fault):
        # YAML reads bare yes/no/on/off/true/false as true or false.
        r.problems.append(f"{r.where}: put text values like \"OFF\" or \"yes\" in quotes")
    return rule


def _robot(data: dict, defaults: dict, where: str, problems: list[str], env: dict) -> RobotMap:
    def section(name):
        own, shared = data.get(name), defaults.get(name)
        if isinstance(own, dict) and isinstance(shared, dict):
            return {**shared, **own}
        return own if own is not None else shared

    _Reader(data, where.rstrip("."), problems, SECTIONS)  # unknown top-level keys
    robot = _Reader(section("robot"), f"{where}robot", problems, {"name", "namespace", "domain_id"})
    name = robot.str("name") or env.get("STYRI_ROBOT_NAME") or os.uname().nodename
    namespace = robot.str("namespace", "") or ""
    domain = robot.num("domain_id")
    if domain is not None and not (0 <= domain <= 232 and domain == int(domain)):
        problems.append(f"{where}robot.domain_id: must be a whole number from 0 to 232")
        domain = None
    stale = _Reader({"stale_after": section("stale_after")}, where.rstrip("."), problems, {"stale_after"}) \
        .num("stale_after", float(env.get("STYRI_STALE_AFTER") or 5.0), positive=True)

    def off(name):  # `battery: false` turns a built-in tile off
        return section(name) is False

    values: list[Value] = []

    # Battery: percentage and voltage from one topic.
    b = _Reader(None if off("battery") else section("battery"), f"{where}battery", problems,
                {"topic", "percentage", "percentage_scale", "voltage", "stale_after", "min_voltage",
                 "warn_below", "fault_below", "hysteresis"})
    if not off("battery"):
        btopic = resolve(b.topic("topic", "/battery_state"), namespace)
        bstale = b.num("stale_after", stale, positive=True)
        pct = b.path("percentage", "percentage")
        if pct:
            values.append(Value("battery", "Battery", btopic, pct, "%", "number", b.num("percentage_scale", 100.0),
                                Rule(warn_below=b.num("warn_below", 25.0), fault_below=b.num("fault_below", 10.0),
                                     hysteresis=b.num("hysteresis", 2.0)), bstale))
        volts = b.path("voltage", "voltage") if b.data.get("voltage") is not False else None
        if volts:
            values.append(Value("voltage", "Voltage", btopic, volts, "V", "number", 1.0,
                                Rule(warn_below=b.num("min_voltage"), hysteresis=0.2), bstale))

    # CPU temperature: a DiagnosticArray entry, or any field; host only if asked.
    c = _Reader(None if off("cpu_temperature") else section("cpu_temperature"), f"{where}cpu_temperature", problems,
                {"topic", "status_name", "key", "field", "warn_above", "fault_above", "hysteresis",
                 "stale_after", "host_fallback"})
    host_fallback = c.bool("host_fallback", False)
    if not off("cpu_temperature"):
        ctopic = c.topic("topic", "/diagnostics")
        crule = Rule(warn_above=c.num("warn_above", 75.0), fault_above=c.num("fault_above", 85.0),
                     hysteresis=c.num("hysteresis", 2.0))
        cstale = c.num("stale_after", stale, positive=True)
        if ctopic == "host":
            values.append(Value("cpu_temp", "Styri host CPU", None, "", "°C", "number", 1.0, crule, cstale))
        elif c.has("field"):
            if c.has("status_name") or c.has("key"):
                problems.append(f"{where}cpu_temperature: use either field or status_name + key, not both")
            values.append(Value("cpu_temp", "CPU temp", resolve(ctopic, namespace), c.path("field"), "°C",
                                "number", 1.0, crule, cstale))
        else:
            values.append(Value("cpu_temp", "CPU temp", resolve(ctopic, namespace), "", "°C", "number", 1.0,
                                crule, cstale, diag_status=c.str("status_name", "cpu"), diag_key=c.str("key", "temp")))

    # The robot's own status, judged by value lists.
    if section("status") is not None:
        s = _Reader(section("status"), f"{where}status", problems,
                    {"topic", "field", "label", "warn", "fault", "stale_after", "kind"})
        kind = s.str("kind", "text")
        if kind not in ("text", "bool"):
            problems.append(f"{where}status.kind: text or bool")
            kind = "text"
        if not s.has("topic"):
            problems.append(f"{where}status.topic: required")
        else:
            values.append(Value("status", s.str("label", "Status"), resolve(s.topic("topic"), namespace),
                                s.path("field", "data"), "", kind, 1.0, _rule(s, kind), s.num("stale_after", stale,
                                                                                               positive=True)))

    # Up to five custom tiles.
    fields = section("fields")
    if fields is not None:
        if not isinstance(fields, list):
            problems.append(f"{where}fields: expected a list (lines starting with “- ”)")
            fields = []
        if len(fields) > MAX_FIELDS:
            problems.append(f"{where}fields: at most {MAX_FIELDS} custom fields (found {len(fields)})")
            fields = fields[:MAX_FIELDS]
        for i, raw in enumerate(fields):
            f = _Reader(raw, f"{where}fields[{i}]", problems,
                        {"label", "topic", "field", "unit", "kind", "stale_after", "warn", "fault"} | THRESHOLDS)
            kind = f.str("kind", "number")
            if kind not in KINDS:
                problems.append(f"{where}fields[{i}].kind: one of number, text, bool")
                kind = "number"
            for req in ("label", "topic", "field"):
                if not f.has(req):
                    problems.append(f"{where}fields[{i}].{req}: required")
            if f.has("label") and f.has("topic") and f.has("field"):
                values.append(Value(f"field{i + 1}", f.str("label"), resolve(f.topic("topic"), namespace),
                                    f.path("field"), f.str("unit", ""), kind, 1.0, _rule(f, kind),
                                    f.num("stale_after", CUSTOM_STALE_AFTER, positive=True)))

    d = section("diagnostics")
    diag_topic: str | None = "/diagnostics"
    if d is False:
        diag_topic = None
    elif d is not None:
        diag_topic = resolve(_Reader(d, f"{where}diagnostics", problems, {"topic"}).topic("topic", "/diagnostics"),
                             namespace)
    labels = [v.label for v in values if v.key.startswith("field")]
    for dup in {x for x in labels if labels.count(x) > 1}:
        problems.append(f"{where}fields: label “{dup}” is used twice")
    return RobotMap(name=name, namespace=namespace, domain_id=None if domain is None else int(domain),
                    values=tuple(values), diagnostics_topic=diag_topic, host_fallback=host_fallback,
                    stale_after=stale)


def from_dict(data: Any, env: dict | None = None) -> tuple[list[RobotMap], list[str]]:
    """Every robot the file describes, and notes. Raises ConfigError."""
    env = dict(os.environ) if env is None else env
    problems: list[str] = []
    notes: list[str] = []
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(["the file must be a mapping (key: value lines), not a list or text"])
    if "robots" in data:
        entries = data["robots"]
        defaults = {k: v for k, v in data.items() if k != "robots"}
        for k in defaults:
            if k not in SECTIONS:
                problems.append(f"{k}: unknown key")
        if not isinstance(entries, list) or not entries:
            raise ConfigError(problems + ["robots: expected a list with at least one robot"])
        robots = [_robot(e if isinstance(e, dict) else {}, defaults, f"robots[{i}].", problems, env)
                  for i, e in enumerate(entries)]
        names = [r.name for r in robots]
        for dup in {n for n in names if names.count(n) > 1}:
            problems.append(f"robots: name “{dup}” is used twice")
        ids = [(r.namespace.strip("/"), r.domain_id) for r in robots]
        for i, key in enumerate(ids):
            if key in ids[:i]:
                problems.append(f"robots[{i}]: same namespace and domain_id as an earlier robot; give each robot "
                                "its own namespace or domain_id")
    else:
        robots = [_robot(data, {}, "", problems, env)]
    if problems:
        raise ConfigError(problems)
    return robots, notes


def from_env(env: dict | None = None) -> RobotMap:
    """The pre-file behaviour: STYRI_* variables, BatteryState and /diagnostics."""
    env = dict(os.environ) if env is None else env
    data: dict = {"battery": {"topic": env.get("STYRI_BATTERY_TOPIC") or "/battery_state"},
                  "cpu_temperature": {"topic": env.get("STYRI_DIAGNOSTICS_TOPIC") or "/diagnostics"},
                  "diagnostics": {"topic": env.get("STYRI_DIAGNOSTICS_TOPIC") or "/diagnostics"}}
    if (env.get("STYRI_MIN_VOLTAGE") or "").strip():
        data["battery"]["min_voltage"] = float(env["STYRI_MIN_VOLTAGE"])
    if (env.get("STYRI_CPU_HOST_FALLBACK") or "").strip().lower() in ("1", "true", "yes"):
        data["cpu_temperature"]["host_fallback"] = True
    return from_dict(data, env)[0][0]


def config_path(env: dict | None = None) -> str | None:
    env = dict(os.environ) if env is None else env
    if env.get("STYRI_CONFIG"):
        return env["STYRI_CONFIG"]
    return DEFAULT_PATH if Path(DEFAULT_PATH).is_file() else None


def load_file(path: str, env: dict | None = None) -> tuple[list[RobotMap], list[str]]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError([f"can't read {path}: {exc.strerror or exc}"]) from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        raise ConfigError([f"not valid YAML{where}: {getattr(exc, 'problem', None) or exc}"]) from None
    return from_dict(data, env)


def load(path: str | None = None, env: dict | None = None) -> Loaded:
    """What the bridge runs with. A bad file is reported, never fatal."""
    env = dict(os.environ) if env is None else env
    path = path or config_path(env)
    if path is None:
        return Loaded((from_env(env),), "environment")
    try:
        robots, notes = load_file(path, env)
    except ConfigError as exc:
        fallback = replace(from_env(env), values=())
        return Loaded((fallback,), path, error="; ".join(exc.problems))
    return Loaded(tuple(robots), path, tuple(notes))
