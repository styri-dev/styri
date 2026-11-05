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

VERDICTS = {"ok": "OK", "warn": "WARNING", "fault": "FAULT", "unknown": "OFFLINE"}
NO_REPLY_AFTER = 3.0      # seconds after a stop with nothing from the robot
NOT_CONFIRMED_AFTER = 15.0  # seconds after a stop with the robot still moving
STOPPED_SHOWN = 30.0      # seconds "Stopped" stays on screen
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
    # The last Operator stop. Progress lives here, apart from the robot's health.
    stop_sent_at: float | None = None
    stop_replied: bool = False    # the robot has said something since
    stop_done_at: float | None = None  # it reported standing still


@dataclass
class RobotView:
    """One robot the panel shows."""
    index: int
    name: str
    domain: str
    monitor: Monitor
    live: Live = field(default_factory=Live)
    stop_logged: str | None = None  # the last stop status the Activity log heard about

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
        # Without speed feedback nothing can confirm a stop, so nothing may set it moving.
        moves = has_speed_feedback(robot)
        return {"can_teleop": moves and bool(link.cmd_vel), "can_waypoint": moves and bool(link.nav2_action),
                "can_pause": moves and bool(link.pause_topic), "can_cancel": moves and bool(link.nav2_action),
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


def overlay_health(view: RobotView, snap: dict) -> None:
    """A tile can't tell that a robot went offline; the protocol can. In the snapshot, so every
    screen says the same thing. Health only: a stop's progress is `stop_status`."""
    if view.live.online is False:
        snap["health"] = {"level": "unknown", "line": "This robot is offline."}


def has_speed_feedback(robot: RobotMap) -> bool:
    """Can this robot tell Styri it has stopped?"""
    return robot.link.protocol == "vda5050" or bool(robot.link.odom or robot.link.velocity)


def stop_sent(live: Live) -> None:
    live.stop_sent_at, live.stop_replied, live.stop_done_at = time.monotonic(), False, None


def stop_over(live: Live) -> None:
    """Something else has been asked of the robot: the last stop is history."""
    live.stop_sent_at = live.stop_done_at = None


def saw_motion(live: Live, driving: bool) -> None:
    """The robot reported whether it's moving: the only thing that confirms a stop."""
    if live.stop_sent_at is None:
        return
    live.stop_replied = True
    if driving:
        live.stop_done_at = None
    elif live.stop_done_at is None:
        live.stop_done_at = time.monotonic()


def stop_status(view: RobotView, now: float | None = None) -> str | None:
    """sent, stopped, no_reply, not_confirmed or cant_confirm; None with no recent stop."""
    live = view.live
    if live.stop_sent_at is None:
        return None
    now = time.monotonic() if now is None else now
    if not has_speed_feedback(view.map):
        return "cant_confirm"
    if live.stop_done_at is not None:
        return "stopped" if now - live.stop_done_at < STOPPED_SHOWN else None
    waited = now - live.stop_sent_at
    if not live.stop_replied:
        return "no_reply" if waited >= NO_REPLY_AFTER else "sent"
    return "not_confirmed" if waited >= NOT_CONFIRMED_AFTER else "sent"


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
        "capabilities": capabilities(robot, live),
        "limits": {"max_linear": robot.link.max_linear, "max_angular": robot.link.max_angular}, "points": [p[0] for p in robot.link.points],
        "vehicle_stop": live.vehicle_stop, "factsheet": live.factsheet, "stop": stop_status(view),
    }


# ---- ROS 2 messages into Live (duck-typed, so tests need no ROS) --------------

def yaw(q: Any) -> float:
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def ros_pose(live: Live, msg: Any) -> None:
    """geometry_msgs PoseWithCovarianceStamped or PoseStamped, or nav_msgs Odometry."""
    p = msg.pose.pose if hasattr(msg.pose, "pose") else msg.pose
    live.pose = {"x": p.position.x, "y": p.position.y, "theta": yaw(p.orientation),
                 "map_id": getattr(msg.header, "frame_id", "") or "map"}


class TfPose:
    """The robot's pose from tf: map down through its frames to the base, for robots with no pose topic."""
    BASES = ("base_link", "base_footprint")

    def __init__(self, live: Live):
        self.live = live
        self.parents: dict[str, tuple[str, Any]] = {}  # child frame -> parent frame, transform

    def message(self, msg: Any) -> None:
        """tf2_msgs/TFMessage, from /tf or /tf_static."""
        for t in msg.transforms:
            self.parents[t.child_frame_id.lstrip("/")] = (t.header.frame_id.lstrip("/"), t.transform)
        for base in self.BASES:
            pose = self._in_map(base)
            if pose is not None:
                self.live.pose = {"x": pose[0], "y": pose[1], "theta": pose[2], "map_id": "map"}
                return

    def _in_map(self, frame: str) -> tuple[float, float, float] | None:
        x = y = theta = 0.0
        for _ in range(16):  # a chain this long isn't a robot's
            if frame == "map":
                return x, y, theta
            if frame not in self.parents:
                return None
            frame, t = self.parents[frame]
            a = yaw(t.rotation)
            x, y = t.translation.x + math.cos(a) * x - math.sin(a) * y, t.translation.y + math.sin(a) * x + math.cos(a) * y
            theta += a
        return None


def ros_odom(live: Live, msg: Any) -> None:
    linear, angular = msg.twist.twist.linear.x, msg.twist.twist.angular.z
    live.velocity = {"linear": linear, "angular": angular}
    live.driving = abs(linear) > 0.01 or abs(angular) > 0.01
    saw_motion(live, live.driving)


def ros_velocity(live: Live, msg: Any) -> None:
    """geometry_msgs Twist or TwistStamped, for a robot with no Odometry."""
    t = msg.twist if hasattr(msg, "twist") else msg
    live.velocity = {"linear": t.linear.x, "angular": t.angular.z}
    live.driving = abs(t.linear.x) > 0.01 or abs(t.angular.z) > 0.01
    saw_motion(live, live.driving)


def nav2_status(live: Live, msg: Any) -> None:
    """action_msgs/GoalStatusArray: the latest goal is the robot's task."""
    if not msg.status_list:
        live.task_id, live.task_state = None, "idle"
        return
    goal = msg.status_list[-1]
    live.task_id = bytes(goal.goal_info.goal_id.uuid).hex()[:8]
    live.task_state = NAV2_STATES.get(goal.status, "idle")
