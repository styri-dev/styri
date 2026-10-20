"""Simulated robot: kinematics, battery, health. No ROS imports.

A differential-drive base that follows /cmd_vel with acceleration limits
and a robot-side dead-man, a battery that drains faster when moving, a
compute board that warms up, diagnostics, and fault injection: enough to
exercise the operator panel end to end.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Status strings published on /robot_status.
IDLE = "IDLE"
MOVING = "MOVING"
LOW_BATTERY = "LOW_BATTERY"


def _approach(current: float, target: float, max_step: float) -> float:
    return current + max(-max_step, min(max_step, target - current))


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


@dataclass
class Limits:
    max_linear: float = 0.6  # m/s
    max_angular: float = 1.5  # rad/s
    linear_accel: float = 0.8  # m/s^2
    angular_accel: float = 3.0  # rad/s^2
    cmd_timeout: float = 0.5  # s, robot-side dead-man


@dataclass
class SimRobot:
    limits: Limits = field(default_factory=Limits)
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0
    v: float = 0.0
    w: float = 0.0
    battery: float = 0.95  # 0..1
    status: str = IDLE
    # Faults
    overheat: bool = False
    battery_sag: bool = False
    motor_fault: bool = False
    silent_until: float = 0.0
    # Internal
    _cmd: tuple[float, float] = (0.0, 0.0)
    _cmd_at: float = -1e9

    # ---- inputs --------------------------------------------------------

    def command_velocity(self, linear: float, angular: float, now: float) -> None:
        self._cmd = (linear, angular)
        self._cmd_at = now

    def inject_fault(self, fault: str, now: float) -> None:
        """Faults for testing: overheat, battery_sag, battery:<percent>, motor_fault,
        silence:<seconds>, clear."""
        name, _, arg = fault.partition(":")
        if name == "overheat":
            self.overheat = True
        elif name == "battery_sag":
            self.battery_sag = True
        elif name == "battery":
            self.battery = max(0.0, min(1.0, float(arg) / 100))
        elif name == "motor_fault":
            self.motor_fault = True
        elif name == "silence":
            self.silent_until = now + float(arg or 10)
        elif name == "clear":
            self.overheat = self.battery_sag = self.motor_fault = False
            self.silent_until = 0.0
        else:
            raise ValueError(f"unknown fault: {fault}")

    # ---- simulation step --------------------------------------------------

    def _target_velocity(self, now: float) -> tuple[float, float]:
        if now - self._cmd_at > self.limits.cmd_timeout:
            return 0.0, 0.0
        lin, ang = self._cmd
        return (max(-self.limits.max_linear, min(self.limits.max_linear, lin)),
                max(-self.limits.max_angular, min(self.limits.max_angular, ang)))

    def step(self, dt: float, now: float) -> None:
        tv, tw = self._target_velocity(now)
        self.v = _approach(self.v, tv, self.limits.linear_accel * dt)
        self.w = _approach(self.w, tw, self.limits.angular_accel * dt)
        self.theta = _wrap(self.theta + self.w * dt)
        self.x += self.v * math.cos(self.theta) * dt
        self.y += self.v * math.sin(self.theta) * dt

        # ~6 h idle, ~1.5 h driving flat out.
        drain = 4.6e-5 + 1.4e-4 * (abs(self.v) / self.limits.max_linear)
        self.battery = max(0.0, self.battery - drain * dt)
        moving = abs(self.v) > 1e-3 or abs(self.w) > 1e-3
        self.status = MOVING if moving else LOW_BATTERY if self.battery < 0.1 else IDLE

    # ---- outputs ------------------------------------------------------------

    def silent(self, now: float) -> bool:
        return now < self.silent_until

    def battery_reading(self) -> dict:
        voltage = 22.0 + 3.2 * self.battery - (2.5 if self.battery_sag else 0.0)
        return {
            "percentage": self.battery,
            "voltage": voltage,
            "temperature": 31.0 + 6.0 * abs(self.v),
            "current": -(1.6 + 6.0 * abs(self.v)),
            "charging": False,
        }

    def cpu_temperature(self) -> float:
        """The compute board heats up while driving; 'overheat' pushes it past 75 °C."""
        return 52.0 + 8.0 * abs(self.v) / self.limits.max_linear + (26.0 if self.overheat else 0.0)

    def diagnostics(self) -> list[tuple[str, int, str, dict[str, str]]]:
        """(name, level, message, values) like diagnostic_msgs/DiagnosticStatus."""
        cpu = self.cpu_temperature()
        cpu_level = 2 if cpu >= 85 else 1 if cpu >= 75 else 0
        return [
            ("cpu_monitor", cpu_level, ["OK", "High temperature", "Critical temperature"][cpu_level],
             {"temperature": f"{cpu:.1f}"}),
            ("lidar_front", 0, "OK", {"rate_hz": "10.0"}),
            ("motor_left", 0, "OK", {}),
            ("motor_right", 2 if self.motor_fault else 0, "Overcurrent" if self.motor_fault else "OK", {}),
        ]
