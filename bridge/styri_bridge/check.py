"""styri check [styri.yaml]: is this mapping right for the robots on this network?

Validates the file, listens to the live topics and the MQTT broker for a few
seconds, then prints PASS or FAIL for every mapping, broker, VDA 5050 vehicle,
node graph and control setting, with close matches for topics it can't find.
Exit code 0 when everything passes, 1 when a line fails, 2 when the file itself
can't be used. Like a view-only panel, it only listens: it never sends anything.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Callable

from . import __version__, mapping
from .config import Config
from .model import RobotView
from .monitor import MISSING_GRACE, Monitor
from .sitemap import GraphError, Graph

Out = Callable[[str], None]

CUSTOM_TYPES = "https://github.com/styri-dev/styri/blob/main/docs/MAPPING.md#your-own-message-types"


def _package(type_name: str) -> str:
    return type_name.split("/", 1)[0]


def _shown(row: dict) -> str:
    v = row.get("value")
    if v is None:
        return ""
    if row.get("kind") == "bool":
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") + (f" {row['unit']}" if row.get("unit") else "")
    return str(v)


def report(robot: mapping.RobotMap, rows: list[dict], out: Out) -> int:
    """Print one robot's mappings. Returns how many failed."""
    failed = 0
    where = ", ".join(x for x in (f"namespace {robot.namespace}" if robot.namespace else "",
                                  f"domain {robot.domain_id}" if robot.domain_id is not None
                                  else f"domain {os.environ.get('ROS_DOMAIN_ID', '0')}") if x)
    out(f"\n{robot.name} ({where})")
    for row in rows:
        ok = row["status"] == "ok"
        failed += not ok
        if ok:
            detail = f"= {_shown(row)}" if _shown(row) else row["detail"]
        elif row["status"] == "missing" and row["topic"]:
            detail = "not on the network." + (f" Did you mean {', '.join(row['suggestions'])}?"
                                              if row["suggestions"] else "")
        elif row["status"] == "waiting":
            detail = "on the network, but nothing was published while listening."
        elif row.get("missing_type"):
            detail = f"its type, {row['missing_type']}, isn't installed here, so Styri can't read it."
        else:
            detail = row["detail"]
        out(f"  {'PASS' if ok else 'FAIL'}  {row['label']:<20} {row['where']}  {detail}".rstrip())
        if row.get("missing_type"):
            out(f"        Add the {_package(row['missing_type'])} package as a message overlay: {CUSTOM_TYPES}")
    return failed


def unknown_types(monitors: list[Monitor]) -> dict[str, int]:
    """Packages of the types seen on the network but not installed here, with topic counts."""
    names: dict[str, str] = {}
    for m in monitors:
        names |= {t.name: t.type for t in m.topics.values() if not t.supported}
    counts: dict[str, int] = {}
    for type_name in names.values():
        counts[_package(type_name)] = counts.get(_package(type_name), 0) + 1
    return counts


Line = tuple[bool | None, str, str]  # passed (None: a warning, not a failure), what, detail


def show(lines: list[Line], out: Out) -> int:
    """Print PASS/FAIL lines. Returns how many failed."""
    for ok, what, detail in lines:
        out(f"  {'WARN' if ok is None else 'PASS' if ok else 'FAIL'}  {what:<20} {detail}".rstrip())
    return sum(ok is False for ok, _, _ in lines)


class Quiet:
    def add(self, kind, msg, source):
        pass


def vehicle_lines(v, seconds: float) -> list[Line]:
    """One VDA vehicle: connection seen, state cadence, schema-valid, factsheet present."""
    topics = v.view.monitor.topics
    connection, state = topics["connection"], topics["state"]
    now = v.view.monitor.clock()
    lines: list[Line] = [(connection.last is not None and v.view.live.online is True, "Connection",
                          "ONLINE" if v.view.live.online else
                          "no ONLINE message seen. Check the vehicle's broker address and login.")]
    if state.last is None:
        lines.append((False, "State", f"nothing in {seconds:g} s."))
    else:
        rate = state.rate(now)
        lines.append((True, "State", f"{rate:.1f} messages a second" if rate else "seen once"))
    invalid = sorted(v.invalid_seen)
    lines.append((not invalid, "Schema", "valid" if not invalid else f"invalid {', '.join(invalid)} messages: see the log."))
    lines.append((v.view.live.factsheet is not None, "Factsheet", "present" if v.view.live.factsheet is not None
                  else "none retained on the broker. Styri asks for it once control is on."))
    return lines


def _listen(client, seconds: float) -> None:
    async def go():
        task = asyncio.create_task(client.run())
        await asyncio.sleep(seconds)
        task.cancel()
    asyncio.run(go())


def check_vda(robots: list[mapping.RobotMap], settings: mapping.Settings, graph, seconds: float, out: Out) -> tuple[int, int, set[str]]:
    """Broker and vehicles. Returns failed, total and the map ids vehicles report."""
    from .vda.client import VdaClient  # only with VDA 5050 robots
    views = [RobotView(i, r.name, "", Monitor(Quiet(), r)) for i, r in enumerate(robots)]
    client = VdaClient(views, settings, Quiet(), graph)  # control off: it can't publish
    args = client._client_args()
    _listen(client, seconds)
    reached = client.seen_broker
    where = f"{args['hostname']}:{args['port']}"
    out("\nMQTT broker")
    failed = show([(reached, "Broker", f"{where} reachable" if reached else
                    f"{where} not reachable. The bundled broker runs with the panel: start Styri first.")], out)
    total, maps = 1, set()
    for v in client.vehicles.values():
        link = v.view.map.link
        out(f"\n{v.view.name} (VDA 5050, {link.manufacturer}/{link.serial})")
        lines = vehicle_lines(v, seconds)
        failed += show(lines, out)
        total += len(lines)
        if v.view.live.pose:
            maps.add(v.view.live.pose["map_id"])
    for manufacturer, serial in sorted(client.unconfigured):
        out(f"Seen on broker, not configured: {manufacturer}/{serial}")
    return failed, total, maps


def graph_lines(graph_path: str, maps: set[str]) -> tuple[list[Line], Graph | None]:
    try:
        graph = Graph.load(graph_path)
    except GraphError as exc:
        return [(False, "Graph", str(exc))], None
    lines: list[Line] = [(True, "Graph", f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")]
    if maps:
        unknown = sorted(graph.maps() - maps)
        lines.append((not unknown, "Maps", f"every node is on a known map ({', '.join(sorted(maps))})" if not unknown else
                      f"nodes on {', '.join(unknown)}, which no vehicle reports. Vehicles report {', '.join(sorted(maps))}."))
    return lines, graph


def control_lines(settings: mapping.Settings, robots: list[mapping.RobotMap], monitors: dict, audit_db: str,
                  env: dict | None = None) -> list[Line]:
    """Is the control config complete, and does what it allows exist on the network?"""
    env = os.environ if env is None else env
    has_password = bool(env.get("STYRI_ADMIN_PASSWORD")) or (Path(audit_db).parent / "users.json").is_file()
    lines: list[Line] = [(True, "Control", "enabled"),
                         (has_password, "Admin password", "set" if has_password else
                          "not set. Set STYRI_ADMIN_PASSWORD, or use the first-run screen.")]
    for r in robots:
        link = r.link
        if link.protocol != "ros2":
            continue
        topics = sorted(monitors[r.name].topics) if r.name in monitors else []

        def found(name: str, what: str, needle: str) -> Line:
            ok = needle in topics
            hint = mapping.suggest(needle, topics)
            return (ok, f"{r.name} {what}", name if ok else
                    f"{name} not on the network." + (f" Did you mean {', '.join(hint)}?" if hint else ""))
        if link.cmd_vel:
            lines.append(found(link.cmd_vel, "cmd_vel", link.cmd_vel))
        if link.nav2_action:
            lines.append(found(link.nav2_action, "Nav2 action", link.nav2_status()))
        if not (link.cmd_vel or link.nav2_action):
            lines.append((True, r.name, "view only: nothing whitelisted"))
        elif not (link.odom or link.velocity):
            lines.append((None, f"{r.name} speed", "no odom or velocity topic: Operator stop only, and it can't "
                                                   "be confirmed. Add one to drive or send this robot."))
    return lines


def run(path: str | None, seconds: float = 5.0, out: Out = print) -> int:
    path = path or mapping.config_path()
    out(f"Styri v{__version__} check · {path or 'no file: the STYRI_* environment defaults'}")
    for overlay in filter(None, os.environ.get("STYRI_OVERLAYS", "").split(":")):
        out(f"Message overlay: {overlay}")
    settings = mapping.Settings()
    if path:
        try:
            robots, notes = mapping.load_file(path)
            settings = mapping.load(path).settings
        except mapping.ConfigError as exc:
            out(f"\nThe file can't be used ({len(exc.problems)} problem{'s' * (len(exc.problems) > 1)}):")
            for p in exc.problems:
                out(f"  - {p}")
            return 2
    else:
        robots, notes = [mapping.from_env()], []
    for note in notes:
        out(f"Note: {note}")

    vda_robots = [r for r in robots if r.link.protocol == "vda5050"]
    robots = [r for r in robots if r.link.protocol == "ros2"]
    failed = total = 0
    maps: set[str] = set()
    if vda_robots or settings.vda_used:
        vda_failed, vda_total, maps = check_vda(vda_robots, settings, None, seconds, out)
        failed, total = failed + vda_failed, total + vda_total
    if settings.graph:
        out("\nSite")
        lines, _ = graph_lines(settings.graph, maps)
        failed, total = failed + show(lines, out), total + len(lines)
    if not robots:
        if settings.control:
            out("\nControl")
            lines = control_lines(settings, vda_robots, {}, Config.from_env(path).audit_db)
            failed, total = failed + show(lines, out), total + len(lines)
        out(f"\n{total - failed} of {total} checks pass." + ("" if not failed else " Fix the FAIL lines, then run styri check again."))
        return 1 if failed else 0

    from .ros_node import RosRuntime  # needs ROS 2; the file checks above don't

    cfg = Config.from_env(path)
    runtimes, monitors = [], []
    try:
        for i, robot in enumerate(robots):
            monitor = Monitor(Quiet(), robot)
            runtime = RosRuntime(cfg, monitor, name=f"styri_check_{os.getpid()}_{i}")
            runtime.start()
            runtimes.append(runtime)
            monitors.append(monitor)
        out(f"Listening for {seconds:g} s…")
        time.sleep(seconds)
        for robot, monitor in zip(robots, monitors):
            monitor.started -= MISSING_GRACE  # discovery is over: unseen now means missing
            rows = monitor.evaluate()["mappings"]
            failed += report(robot, rows, out)
            total += len(rows)
        unknown = unknown_types(monitors)
        if unknown:
            n = sum(unknown.values())
            out(f"\nNote: {n} topic{'s' * (n > 1)} on the network use{'s' * (n == 1)} message types not installed here "
                f"({', '.join(f'{pkg} ×{k}' for pkg, k in sorted(unknown.items()))}). Styri counts their rate but "
                f"can't show their contents. To add them: {CUSTOM_TYPES}")
        if settings.control:
            out("\nControl")
            lines = control_lines(settings, robots + vda_robots, {r.name: m for r, m in zip(robots, monitors)}, cfg.audit_db)
            failed, total = failed + show(lines, out), total + len(lines)
    finally:
        for runtime in runtimes:
            runtime.shutdown()
    out(f"\n{total - failed} of {total} mappings pass." + ("" if not failed else
        " Fix the FAIL lines, then run styri check again."))
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="styri check", description=__doc__.split("\n\n")[0])
    parser.add_argument("file", nargs="?", help="mapping file (default: STYRI_CONFIG or /etc/styri/styri.yaml)")
    parser.add_argument("--seconds", type=float, default=5.0, help="how long to listen (default 5)")
    args = parser.parse_args(argv)
    return run(args.file, args.seconds)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
