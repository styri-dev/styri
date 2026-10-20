"""Host vitals (CPU temperature, load, memory) read from /sys and /proc.

These come from the robot PC itself rather than ROS, so the operator still
sees them when the ROS graph is down.
"""

from __future__ import annotations

import asyncio
import glob
import os
from typing import Callable

def _cpu_temp_c() -> float | None:
    temps = []
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            with open(path) as f:
                temps.append(int(f.read().strip()) / 1000)
        except (OSError, ValueError):
            continue
    # Report the hottest zone: that is the one that throttles first.
    return round(max(temps), 1) if temps else None


def _mem_used_pct() -> float | None:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, value = line.split(":", 1)
                info[key] = int(value.split()[0])
        return round(100 * (1 - info["MemAvailable"] / info["MemTotal"]), 1)
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None


def read_vitals() -> dict:
    try:
        load1 = round(os.getloadavg()[0], 2)
    except OSError:
        load1 = None
    cpus = os.cpu_count() or 1
    return {
        "cpu_temperature": _cpu_temp_c(),
        "load_1m": load1,
        "load_pct": None if load1 is None else round(min(100.0, 100 * load1 / cpus), 1),
        "cpu_count": cpus,
        "memory_used_pct": _mem_used_pct(),
    }


async def run(on_vitals: Callable[[dict], None], period: float = 1.0) -> None:
    while True:
        on_vitals(read_vitals())
        await asyncio.sleep(period)
