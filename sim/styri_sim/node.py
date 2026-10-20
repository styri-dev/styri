"""ROS 2 wrapper around SimRobot."""

from __future__ import annotations

import logging
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from sensor_msgs.msg import BatteryState, LaserScan
from std_msgs.msg import String

from .model import Limits, SimRobot

logger = logging.getLogger("styri_sim")

FAULT_TOPIC = "/styri_sim/fault"
PHYSICS_HZ = 50


class SimNode(Node):
    def __init__(self, robot: SimRobot):
        super().__init__("styri_sim")
        self.robot = robot
        reliable = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10)

        self.create_subscription(Twist, "/cmd_vel", self._on_cmd_vel, reliable)
        self.create_subscription(String, FAULT_TOPIC, self._on_fault, reliable)

        self._battery_pub = self.create_publisher(BatteryState, "/battery_state", reliable)
        self._diag_pub = self.create_publisher(DiagnosticArray, "/diagnostics", reliable)
        self._status_pub = self.create_publisher(String, "/robot_status", reliable)
        self._odom_pub = self.create_publisher(Odometry, "/odom", reliable)
        self._scan_pub = self.create_publisher(LaserScan, "/scan", reliable)

        self._last = time.monotonic()
        self.create_timer(1 / PHYSICS_HZ, self._step)
        self.create_timer(1.0, self._publish_battery)
        self.create_timer(0.5, self._publish_status)
        self.create_timer(0.1, self._publish_odom)
        self.create_timer(1.0, self._publish_diagnostics)
        self.create_timer(0.1, self._publish_scan)
        logger.info("Sim robot up")

    def _on_cmd_vel(self, msg: Twist) -> None:
        self.robot.command_velocity(msg.linear.x, msg.angular.z, time.monotonic())

    def _on_fault(self, msg: String) -> None:
        try:
            self.robot.inject_fault(msg.data, time.monotonic())
            logger.info("fault injected: %s", msg.data)
        except ValueError as exc:
            logger.warning("%s", exc)

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
    """One-shot publish to the fault topic (used by tests and humans)."""
    rclpy.init()
    node = Node("styri_sim_fault")
    pub = node.create_publisher(String, FAULT_TOPIC, QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=1))
    deadline = time.monotonic() + 5
    while pub.get_subscription_count() == 0 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    if pub.get_subscription_count() == 0:
        raise SystemExit("sim robot not found on this ROS_DOMAIN_ID")
    pub.publish(String(data=fault))
    # Reliable QoS: wait until the robot has acknowledged it, so exiting
    # straight away can't drop the message (it did on slow CI machines).
    if not pub.wait_for_all_acked(Duration(seconds=5)):
        raise SystemExit("sim robot did not acknowledge the fault")
    node.destroy_node()
    rclpy.try_shutdown()


def print_pose() -> None:
    """Print the robot's current pose and speed from /odom as JSON (for tests)."""
    import json

    rclpy.init()
    node = Node("styri_sim_pose")
    got: list[Odometry] = []
    node.create_subscription(Odometry, "/odom", got.append, QoSProfile(
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
