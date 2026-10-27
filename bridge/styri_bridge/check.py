"""styri check [styri.yaml]: is this mapping right for the robot on this network?

Validates the file, listens to the live topics for a few seconds, then prints
PASS or FAIL for every mapping, with close matches for topics it can't find.
Exit code 0 when everything passes, 1 when a mapping fails, 2 when the file
itself can't be used. Like the panel, it only subscribes: it never publishes.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable

from . import __version__, mapping
from .config import Config
from .monitor import MISSING_GRACE, Monitor

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


def run(path: str | None, seconds: float = 5.0, out: Out = print) -> int:
    path = path or mapping.config_path()
    out(f"Styri v{__version__} check · {path or 'no file: the STYRI_* environment defaults'}")
    for overlay in filter(None, os.environ.get("STYRI_OVERLAYS", "").split(":")):
        out(f"Message overlay: {overlay}")
    if path:
        try:
            robots, notes = mapping.load_file(path)
        except mapping.ConfigError as exc:
            out(f"\nThe file can't be used ({len(exc.problems)} problem{'s' * (len(exc.problems) > 1)}):")
            for p in exc.problems:
                out(f"  - {p}")
            return 2
    else:
        robots, notes = [mapping.from_env()], []
    for note in notes:
        out(f"Note: {note}")

    from .ros_node import RosRuntime  # needs ROS 2; the file checks above don't

    class Quiet:
        def add(self, kind, msg, source):
            pass

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
        failed = total = 0
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
