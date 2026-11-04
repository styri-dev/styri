"""The commands a browser may send, checked before anything else sees them."""

from __future__ import annotations

import math
from dataclasses import dataclass

ROBOT_COMMANDS = ("TELEOP", "TELEOP_RELEASE", "GOAL", "PAUSE", "RESUME", "CANCEL", "OPERATOR_STOP")
FLEET_COMMANDS = ("OPERATOR_STOP_ALL",)
SESSION_ACTIONS = ("LOGIN", "SETUP", "LOGOUT", "AUDIT")


class CommandError(ValueError):
    """Not an allowed command."""


@dataclass(frozen=True)
class Goal:
    x: float | None = None
    y: float | None = None
    theta: float = 0.0
    node: str | None = None
    point: str | None = None

    def payload(self) -> dict:
        return {k: v for k, v in vars(self).items() if v is not None}


def number(data: dict, name: str, default: float | None = None) -> float:
    value = data.get(name, default)
    # bool is an int subclass.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CommandError(f"'{name}' must be a number")
    return float(value)


def text(data: dict, name: str, limit: int = 128) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value or len(value) > limit:
        raise CommandError(f"'{name}' must be a short text")
    return value


def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def goal(data: dict) -> Goal:
    """A place: coordinates on the site map, a graph node, or a saved point."""
    if data.get("node") is not None:
        return Goal(node=text(data, "node"))
    if data.get("point") is not None:
        return Goal(point=text(data, "point"))
    return Goal(x=number(data, "x"), y=number(data, "y"), theta=number(data, "theta", 0.0))
