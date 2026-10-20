"""Fake robot for developing the UI without ROS 2 or Docker.

Run with:  STYRI_AUDIT_DB=./audit.db python -m styri_bridge --fake
It feeds the monitor the same way the ROS node does, with a small set of
plausible topics. For a real DDS robot use the sim (docker compose up).
"""

from __future__ import annotations

import asyncio
import math
import time

from .monitor import Monitor

TOPICS = [
    ("/battery_state", "sensor_msgs/msg/BatteryState", 1.0),
    ("/diagnostics", "diagnostic_msgs/msg/DiagnosticArray", 1.0),
    ("/odom", "nav_msgs/msg/Odometry", 20.0),
    ("/scan", "sensor_msgs/msg/LaserScan", 10.0),
    ("/cmd_vel", "geometry_msgs/msg/Twist", 0.0),
    ("/rosout", "rcl_interfaces/msg/Log", 1.0),
    ("/parameter_events", "rcl_interfaces/msg/ParameterEvent", 0.0),
]


class FakeRobot:
    def __init__(self, monitor: Monitor):
        self.monitor = monitor
        self.battery = 0.76

    async def run(self, tick: float = 0.05) -> None:
        self.monitor.discovered([(n, t) for n, t, _ in TOPICS], lambda _t: True)
        next_at = {n: 0.0 for n, _, hz in TOPICS if hz}
        while True:
            now = time.monotonic()
            t = time.time()
            for name, _type, hz in TOPICS:
                if not hz or now < next_at[name]:
                    continue
                next_at[name] = now + 1 / hz
                payload = self._payload(name, t)
                self.monitor.message(name, payload, now)
                if name == "/battery_state":
                    self.battery = max(0.05, self.battery - 0.0002)
                    self.monitor.battery_state(self.battery * 100, payload["voltage"], now)
                elif name == "/diagnostics":
                    temp = 58.0 + 2.0 * math.sin(t / 20)
                    self.monitor.diagnostics([("cpu_monitor", 0, "OK", {"temperature": f"{temp:.1f}"})], now)
            await asyncio.sleep(tick)

    def _payload(self, name: str, t: float) -> dict:
        if name == "/battery_state":
            return {"voltage": round(21.6 + 3.9 * self.battery, 2), "current": -1.84,
                    "percentage": round(self.battery, 3), "power_supply_status": 2, "present": True}
        if name == "/diagnostics":
            return {"status": [{"name": "cpu_monitor", "level": 0, "message": "OK",
                                "values": [{"key": "temperature", "value": f"{58.0 + 2.0 * math.sin(t / 20):.1f}"}]}]}
        if name == "/odom":
            return {"pose": {"position": {"x": round(math.cos(t / 10), 3), "y": round(math.sin(t / 10), 3)}},
                    "twist": {"linear": {"x": 0.1}, "angular": {"z": 0.1}}}
        if name == "/scan":
            return {"angle_min": -3.14, "angle_max": 3.14, "ranges": "[360 values]"}
        return {"msg": "fake"}
