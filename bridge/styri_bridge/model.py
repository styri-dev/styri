"""One model for every robot, whatever protocol it speaks.

The ROS node and the VDA 5050 client both feed a `RobotView`; the WebSocket API
and the UI read `describe()` and never ask which protocol a robot uses. Health
comes from the robot's Monitor, the rest from `Live`. No ROS imports.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from .mapping import RobotMap
from .monitor import Monitor
from .sitemap import to_site

VERDICTS = {"ok": "OK", "warn": "WARNING", "fault": "FAULT", "unknown": "NO DATA"}
# action_msgs/GoalStatus: accepted, executing and canceling count as active.
NAV2_STATES = {1: "active", 2: "active", 3: "active", 4: "done", 5: "idle", 6: "failed"}


@dataclass
class Live:
    """What the robot's adapter last reported, beyond the mapped tiles."""
    pose: dict | None = None      # x, y, theta, map_id
    velocity: dict | None = None  # linear, angular
    driving: bool | None = None
    paused: bool = False
    task_id: str | None = None
    task_state: str = "idle"      # idle, active, paused, failed, done
    last_node: str | None = None
    route: list = field(default_factory=list)  # node ids still to reach
    errors: list = field(default_factory=list)  # {type, level, description}
    warnings: list = field(default_factory=list)  # adapter's own, in words
    online: bool | None = None    # None: this protocol doesn't say
    factsheet: dict | None = None
    vehicle_stop: bool = False    # the vehicle reports its own safety stop is active


@dataclass
class RobotView:
    """One robot the panel shows."""
    index: int
    name: str
    domain: str
    monitor: Monitor
    live: Live = field(default_factory=Live)

    @property
    def map(self) -> RobotMap:
        return self.monitor.robot

    @property
    def id(self) -> str:
        return self.name


def capabilities(robot: RobotMap, live: Live) -> dict:
    """Which controls this robot supports. The UI shows no others."""
    link = robot.link
    if link.protocol == "ros2":
        return {"can_teleop": bool(link.cmd_vel), "can_waypoint": bool(link.nav2_action),
                "can_pause": bool(link.pause_topic), "can_cancel": bool(link.nav2_action),
                "can_stop": bool(link.cmd_vel or link.nav2_action)}
    allowed = set(link.instant_actions)
    if live.factsheet is not None:
        listed = {a.get("actionType") for a in live.factsheet.get("protocolFeatures", {}).get("agvActions", [])
                  if isinstance(a, dict)}
        # An empty list says nothing; a list without the action says the vehicle can't do it.
        allowed = allowed & listed if listed else allowed
    return {"can_teleop": False, "can_waypoint": True,
            "can_pause": {"startPause", "stopPause"} <= allowed, "can_cancel": "cancelOrder" in allowed,
            # Operator stop stays on whatever the factsheet says: the vehicle may still honor it.
            "can_stop": bool({"startPause", "cancelOrder"} & set(link.instant_actions))}


def is_stale(view: RobotView, snap: dict) -> bool:
    if view.live.online is False:
        return True
    return snap["health"]["level"] == "unknown" or not snap["robot_found"]


def describe(view: RobotView, snap: dict) -> dict:
    """The unified model for one robot, from its latest snapshot."""
    robot, live = view.map, view.live
    age = snap["last_message"]["age"]
    tile = lambda key: snap[key]["value"] if isinstance(snap[key].get("value"), (int, float)) else None  # noqa: E731
    return {
        "index": view.index, "id": view.id, "name": view.name, "protocol": robot.link.protocol,
        "vendor": robot.link.vendor, "model": robot.link.model,
        "verdict": VERDICTS[snap["health"]["level"]], "reason": snap["health"]["line"],
        "battery": tile("battery"), "voltage": tile("voltage"), "errors": live.errors, "warnings": live.warnings,
        "last_seen": None if age is None else round(time.time() - age, 1), "stale": is_stale(view, snap),
        "pose": to_site(live.pose, robot.link.map_offset), "velocity": live.velocity, "driving": live.driving, "paused": live.paused,
        "task": {"id": live.task_id, "state": "paused" if live.paused and live.task_state == "active" else live.task_state,
                 "last_node": live.last_node, "route": live.route},
        "capabilities": capabilities(robot, live), "points": [p[0] for p in robot.link.points],
        "vehicle_stop": live.vehicle_stop, "factsheet": live.factsheet,
    }


# ---- ROS 2 messages into Live (duck-typed, so tests need no ROS) --------------

def yaw(q: Any) -> float:
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def ros_pose(live: Live, msg: Any) -> None:
    """geometry_msgs PoseWithCovarianceStamped or PoseStamped, or nav_msgs Odometry."""
    p = msg.pose.pose if hasattr(msg.pose, "pose") else msg.pose
    live.pose = {"x": p.position.x, "y": p.position.y, "theta": yaw(p.orientation),
                 "map_id": getattr(msg.header, "frame_id", "") or "map"}


def ros_odom(live: Live, msg: Any) -> None:
    linear, angular = msg.twist.twist.linear.x, msg.twist.twist.angular.z
    live.velocity = {"linear": linear, "angular": angular}
    live.driving = abs(linear) > 0.01 or abs(angular) > 0.01


def nav2_status(live: Live, msg: Any) -> None:
    """action_msgs/GoalStatusArray: the latest goal is the robot's task."""
    if not msg.status_list:
        live.task_id, live.task_state = None, "idle"
        return
    goal = msg.status_list[-1]
    live.task_id = bytes(goal.goal_info.goal_id.uuid).hex()[:8]
    live.task_state = NAV2_STATES.get(goal.status, "idle")
