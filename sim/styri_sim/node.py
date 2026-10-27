"""ROS 2 wrapper around SimRobot."""

from __future__ import annotations

import logging
import math
import os
import time

import rclpy
from action_msgs.msg import GoalInfo, GoalStatus, GoalStatusArray
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from sensor_msgs.msg import BatteryState, LaserScan
from std_msgs.msg import String

from .model import Limits, SimRobot

try:  # Nav2's own messages, when installed (the sim image has them)
    from nav2_msgs.action import NavigateToPose
except ImportError:
    NavigateToPose = None

logger = logging.getLogger("styri_sim")

FAULT_TOPIC = "/styri_sim/fault"
# Faults can also be dropped into this directory as files (one fault per
# file). `python3 -m styri_sim fault` uses it: no DDS discovery race, and it
# can wait until the robot has actually applied the fault.
FAULT_DIR = "/tmp/styri_sim_faults"
PHYSICS_HZ = 50
# A Nav2-style goal cycle on the NavigateToPose action's topics: a goal runs
# for NAV_RUN s, then succeeds (every third one fails), then NAV_GAP s idle.
NAV_RUN, NAV_GAP = 8.0, 4.0


class SimNode(Node):
    def __init__(self, robot: SimRobot, namespace: str | None = None):
        # SIM_NAMESPACE=/amr2 puts every topic under /amr2, like a namespaced fleet robot.
        super().__init__("styri_sim", namespace=namespace or os.environ.get("SIM_NAMESPACE") or None)
        self.robot = robot
        reliable = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10)

        self.create_subscription(Twist, "cmd_vel", self._on_cmd_vel, reliable)
        self.create_subscription(String, FAULT_TOPIC, self._on_fault, reliable)

        self._battery_pub = self.create_publisher(BatteryState, "battery_state", reliable)
        self._diag_pub = self.create_publisher(DiagnosticArray, "diagnostics", reliable)
        self._status_pub = self.create_publisher(String, "robot_status", reliable)
        self._odom_pub = self.create_publisher(Odometry, "odom", reliable)
        self._scan_pub = self.create_publisher(LaserScan, "scan", reliable)

        # Like a real action server: status latched (reliable, transient
        # local) and published only on change; feedback while a goal runs.
        latched = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             history=HistoryPolicy.KEEP_LAST, depth=1)
        self._goal_pub = self.create_publisher(GoalStatusArray, "navigate_to_pose/_action/status", latched)
        self._feedback_pub = None if NavigateToPose is None else self.create_publisher(
            NavigateToPose.Impl.FeedbackMessage, "navigate_to_pose/_action/feedback", reliable)
        self._goals: list[GoalStatus] = []
        self._goal_n = 0
        self._goal_started = time.monotonic() + NAV_GAP  # the first goal after a short idle
        self.create_timer(0.5, self._navigate)

        self._last = time.monotonic()
        self.create_timer(1 / PHYSICS_HZ, self._step)
        self.create_timer(1.0, self._publish_battery)
        self.create_timer(0.5, self._publish_status)
        self.create_timer(0.1, self._publish_odom)
        self.create_timer(1.0, self._publish_diagnostics)
        self.create_timer(0.1, self._publish_scan)
        os.makedirs(FAULT_DIR, exist_ok=True)
        self.create_timer(0.05, self._poll_fault_files)
        logger.info("Sim robot up")

    def _on_cmd_vel(self, msg: Twist) -> None:
        self.robot.command_velocity(msg.linear.x, msg.angular.z, time.monotonic())

    def _on_fault(self, msg: String) -> None:
        try:
            self.robot.inject_fault(msg.data, time.monotonic())
            logger.info("fault injected: %s", msg.data)
        except ValueError as exc:
            logger.warning("%s", exc)

    def _poll_fault_files(self) -> None:
        for name in sorted(os.listdir(FAULT_DIR)):
            if not name.endswith(".fault"):
                continue  # still being written
            path = os.path.join(FAULT_DIR, name)
            try:
                with open(path) as f:
                    fault = f.read().strip()
                self.robot.inject_fault(fault, time.monotonic())
                logger.info("fault injected: %s", fault)
            except (OSError, ValueError) as exc:
                logger.warning("%s", exc)
            finally:
                try:
                    os.remove(path)  # removal is the acknowledgement
                except OSError:
                    pass

    def _step(self) -> None:
        now = time.monotonic()
        self.robot.step(now - self._last, now)
        self._last = now

    def _publish_battery(self) -> None:
        if self.robot.silent(time.monotonic()):
            return
        r = self.robot.battery_reading()
        msg = BatteryState()
        msg.percentage = float(r["percentage"])
        msg.voltage = float(r["voltage"])
        msg.temperature = float(r["temperature"])
        msg.current = float(r["current"])
        msg.charge = math.nan  # unknown, like many real drivers report
        msg.power_supply_status = BatteryState.POWER_SUPPLY_STATUS_DISCHARGING
        msg.present = True
        self._battery_pub.publish(msg)

    def _publish_diagnostics(self) -> None:
        if self.robot.silent(time.monotonic()):
            return
        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        for name, level, message, values in self.robot.diagnostics():
            msg.status.append(DiagnosticStatus(
                level=bytes([level]), name=name, message=message, hardware_id="sim-01",
                values=[KeyValue(key=k, value=v) for k, v in values.items()]))
        self._diag_pub.publish(msg)

    def _publish_scan(self) -> None:
        if self.robot.silent(time.monotonic()):
            return
        msg = LaserScan()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "laser"
        msg.angle_min, msg.angle_max = -math.pi, math.pi
        msg.angle_increment = 2 * math.pi / 360
        msg.range_min, msg.range_max = 0.1, 12.0
        # A 4 x 4 m room around the robot, enough to look real in the preview.
        msg.ranges = [float(min(12.0, 2.0 / max(abs(math.cos(a)), abs(math.sin(a)))))
                      for a in (msg.angle_min + i * msg.angle_increment for i in range(360))]
        self._scan_pub.publish(msg)

    def _publish_status(self) -> None:
        if not self.robot.silent(time.monotonic()):
            self._status_pub.publish(String(data=self.robot.status))

    def _navigate(self) -> None:
        now = time.monotonic()
        running = bool(self._goals) and self._goals[-1].status == GoalStatus.STATUS_EXECUTING
        if not running and now >= self._goal_started:
            self._goal_n += 1
            info = GoalInfo()
            info.goal_id.uuid = [self._goal_n % 256] * 16
            info.stamp = self.get_clock().now().to_msg()
            self._goals = (self._goals + [GoalStatus(goal_info=info, status=GoalStatus.STATUS_EXECUTING)])[-3:]
            self._goal_pub.publish(GoalStatusArray(status_list=self._goals))
        elif running and now >= self._goal_started + NAV_RUN:
            self._goals[-1].status = GoalStatus.STATUS_ABORTED if self._goal_n % 3 == 0 \
                else GoalStatus.STATUS_SUCCEEDED
            self._goal_pub.publish(GoalStatusArray(status_list=self._goals))
            self._goal_started = now + NAV_GAP
        elif running and self._feedback_pub is not None:
            msg = NavigateToPose.Impl.FeedbackMessage()
            msg.goal_id = self._goals[-1].goal_info.goal_id
            msg.feedback.distance_remaining = float(max(0.0, 4.0 * (1 - (now - self._goal_started) / NAV_RUN)))
            self._feedback_pub.publish(msg)

    def _publish_odom(self) -> None:
        if self.robot.silent(time.monotonic()):
            return
        r = self.robot
        msg = Odometry()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "odom"
        msg.child_frame_id = "base_link"
        msg.pose.pose.position.x = r.x
        msg.pose.pose.position.y = r.y
        msg.pose.pose.orientation.z = math.sin(r.theta / 2)
        msg.pose.pose.orientation.w = math.cos(r.theta / 2)
        msg.twist.twist.linear.x = r.v
        msg.twist.twist.angular.z = r.w
        self._odom_pub.publish(msg)


def run() -> None:
    robot = SimRobot(Limits())
    rclpy.init()
    node = SimNode(robot)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


def send_fault(fault: str) -> None:
    """Inject a fault into the sim running in this container (tests and humans).

    Writes the fault as a file the sim polls, then waits until the sim has
    applied it and removed the file.
    """
    if not os.path.isdir(FAULT_DIR):
        raise SystemExit("sim robot isn't running in this container")
    tmp = os.path.join(FAULT_DIR, f"{time.time_ns()}.tmp")
    with open(tmp, "w") as f:
        f.write(fault)
    path = tmp[: -len(".tmp")] + ".fault"
    os.rename(tmp, path)  # atomic: the sim never sees half a fault
    deadline = time.monotonic() + 5
    while os.path.exists(path):
        if time.monotonic() > deadline:
            os.remove(path)
            raise SystemExit("sim robot did not pick up the fault within 5 s")
        time.sleep(0.02)


def print_pose() -> None:
    """Print the robot's current pose and speed from /odom as JSON (for tests)."""
    import json

    rclpy.init()
    node = Node("styri_sim_pose", namespace=os.environ.get("SIM_NAMESPACE") or None)
    got: list[Odometry] = []
    node.create_subscription(Odometry, "odom", got.append, QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=1))
    deadline = time.monotonic() + 5
    while not got and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    node.destroy_node()
    rclpy.try_shutdown()
    if not got:
        raise SystemExit("no /odom from the sim robot")
    m = got[0]
    print(json.dumps({"x": m.pose.pose.position.x, "y": m.pose.pose.position.y,
                      "v": m.twist.twist.linear.x, "w": m.twist.twist.angular.z}))
