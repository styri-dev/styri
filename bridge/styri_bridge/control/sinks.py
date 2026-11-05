"""Where commands go. The only module that gives Styri a way to command a ROS robot.

One RosSink per ROS robot, created only with control on. It publishes only to
the robot's configured `cmd_vel` and `pause_topic`, and uses only its
`nav2_action`: the whitelist in styri.yaml.
"""

from __future__ import annotations

import asyncio
import logging
import math

from ..mapping import RobotMap
from ..sitemap import from_site

logger = logging.getLogger("styri_bridge")

STOP_RATE = 10.0     # Hz
STOP_SECONDS = 2.0


class SinkError(RuntimeError):
    """A command can't be carried out. The message is for the operator."""


def _goal_answered(view, done) -> None:
    """Nav2 says at once whether it takes a goal; the status topic never mentions one it turned down."""
    if not done.result().accepted:
        view.live.goal_rejected = True


class RosSink:
    def __init__(self, node, robot: RobotMap):
        from action_msgs.srv import CancelGoal
        from geometry_msgs.msg import PoseStamped, Twist
        from nav2_msgs.action import NavigateToPose
        from rclpy.action import ActionClient
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Bool

        self.robot, self.node, self._Twist, self._Bool = robot, node, Twist, Bool
        self._PoseStamped, self._NavigateToPose, self._CancelGoal = PoseStamped, NavigateToPose, CancelGoal
        link = robot.link
        reliable = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10)
        self._vel = node.create_publisher(Twist, link.cmd_vel, reliable) if link.cmd_vel else None
        self._pause = node.create_publisher(Bool, link.pause_topic, reliable) if link.pause_topic else None
        self._nav = ActionClient(node, NavigateToPose, link.nav2_action) if link.nav2_action else None
        self._cancel = node.create_client(CancelGoal, f"{link.nav2_action}/_action/cancel_goal") \
            if link.nav2_action else None
        logger.warning("Control is ON for %s", robot.name)

    def velocity(self, linear: float, angular: float) -> None:
        msg = self._Twist()
        msg.linear.x, msg.angular.z = linear, angular
        self._vel.publish(msg)

    async def goal(self, view, x: float, y: float, theta: float) -> None:
        if self._nav is None or not self._nav.server_is_ready():
            raise SinkError("Nav2 isn't answering on this robot")
        x, y, theta = from_site(x, y, theta, self.robot.link.map_offset)
        goal = self._NavigateToPose.Goal()
        goal.pose = self._PoseStamped()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = x, y
        goal.pose.pose.orientation.z, goal.pose.pose.orientation.w = math.sin(theta / 2), math.cos(theta / 2)
        self._nav.send_goal_async(goal).add_done_callback(lambda done: _goal_answered(view, done))

    async def pause(self, view) -> None:
        self._pause.publish(self._Bool(data=True))
        view.live.paused = True

    async def resume(self, view) -> None:
        self._pause.publish(self._Bool(data=False))
        view.live.paused = False

    async def cancel(self, view) -> None:
        if self._cancel is None:
            raise SinkError("this robot has no nav2_action")
        # An empty goal id and stamp cancels every goal, whoever sent it.
        self._cancel.call_async(self._CancelGoal.Request())

    async def operator_stop(self, view) -> None:
        """Cancel active goals, then zero velocity at 10 Hz for 2 s."""
        if self._cancel is not None:
            self._cancel.call_async(self._CancelGoal.Request())
        if self._vel is not None:
            self.velocity(0.0, 0.0)
            asyncio.get_running_loop().create_task(self._hold_zero())

    async def _hold_zero(self) -> None:
        for _ in range(int(STOP_RATE * STOP_SECONDS) - 1):
            await asyncio.sleep(1 / STOP_RATE)
            self.velocity(0.0, 0.0)


class LogSink:
    """With no ROS (the fake robot): logs, sends nothing."""

    def __init__(self, robot: RobotMap):
        self.robot = robot

    def velocity(self, linear: float, angular: float) -> None:
        pass

    async def goal(self, view, x: float, y: float, theta: float) -> None:
        logger.info("%s: goal (%.2f, %.2f)", self.robot.name, x, y)

    async def pause(self, view) -> None:
        logger.info("%s: pause", self.robot.name)

    async def resume(self, view) -> None:
        logger.info("%s: resume", self.robot.name)

    async def cancel(self, view) -> None:
        logger.info("%s: cancel", self.robot.name)

    async def operator_stop(self, view) -> None:
        logger.info("%s: Operator stop", self.robot.name)
