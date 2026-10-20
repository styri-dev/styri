"""ROS 2 side of the bridge. Only this module imports rclpy.

Read-only by construction: the node subscribes and never publishes. It
also turns off what rclpy creates by default (the /rosout logger, the
/parameter_events publisher and the parameter services), so the robot's
graph shows Styri with zero publishers and zero services.
"""

from __future__ import annotations

import logging
import math
import os
import threading

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.convert import message_to_yaml
from rosidl_runtime_py.utilities import get_message

from .config import Config
from .monitor import Monitor

logger = logging.getLogger("styri_bridge")

NODE_NAME = "styri_bridge"
DISCOVERY_PERIOD = 2.0  # seconds
MAX_TOPICS = 300  # a safety cap for very large graphs
BATTERY_TYPE = "sensor_msgs/msg/BatteryState"
DIAGNOSTICS_TYPE = "diagnostic_msgs/msg/DiagnosticArray"


def _finite(value: float) -> float | None:
    """BatteryState uses NaN for 'unknown'."""
    return value if math.isfinite(value) else None


def _hidden(name: str) -> bool:
    return any(part.startswith("_") for part in name.split("/"))


def _message_class(type_name: str):
    try:
        return get_message(type_name)
    except (AttributeError, ModuleNotFoundError, ValueError):
        return None


def decode(type_name: str, raw: bytes) -> str:
    """Latest message as YAML for the Topics tab, long arrays cut short."""
    msg = deserialize_message(raw, get_message(type_name))
    return message_to_yaml(msg, truncate_length=32)


class StyriBridgeNode(Node):
    def __init__(self, cfg: Config, monitor: Monitor):
        super().__init__(NODE_NAME, enable_rosout=False, start_parameter_services=False,
                         # Jazzy's type-description service: harmless, but Core offers no services at all.
                         parameter_overrides=[Parameter("start_type_description_service", value=False)])
        # rclpy always creates a /parameter_events publisher; Styri sets no
        # parameters, so remove it and stay strictly subscribe-only.
        events = getattr(self, "_parameter_event_publisher", None)
        if events is not None:
            self.destroy_publisher(events)
            self._parameter_event_publisher = None
        self.cfg = cfg
        self.monitor = monitor
        # Best effort: matches both reliable and best-effort publishers and
        # never back-pressures the robot. Raw bytes: counting a camera's
        # frames costs nothing; we only decode what someone looks at.
        self._qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=5)
        self._subs = {}
        self._battery_cls = _message_class(BATTERY_TYPE)
        self._diag_cls = _message_class(DIAGNOSTICS_TYPE)
        self.create_timer(DISCOVERY_PERIOD, self._discover)
        logger.info("ROS 2 node online (ROS_DOMAIN_ID=%s, RMW=%s)", os.environ.get("ROS_DOMAIN_ID", "0"),
                    os.environ.get("RMW_IMPLEMENTATION", "default"))

    def _discover(self) -> None:
        graph = [(name, types[0]) for name, types in self.get_topic_names_and_types()
                 if types and not _hidden(name)][:MAX_TOPICS]
        types = dict(graph)
        for name in self.monitor.discovered(graph, lambda t: _message_class(t) is not None):
            cls = _message_class(types[name])
            if cls is None:
                logger.info("Topic %s has type %s, which is not installed here", name, types[name])
                continue
            self._subs[name] = self.create_subscription(
                cls, name, lambda raw, n=name, t=types[name]: self._on_raw(n, t, raw), self._qos, raw=True)

    def _on_raw(self, name: str, type_name: str, raw: bytes) -> None:
        self.monitor.message(name, raw)
        try:
            if name == self.cfg.battery_topic and type_name == BATTERY_TYPE:
                msg = deserialize_message(raw, self._battery_cls)
                pct = _finite(msg.percentage)
                self.monitor.battery_state(None if pct is None else pct * 100, _finite(msg.voltage))
            elif name == self.cfg.diagnostics_topic and type_name == DIAGNOSTICS_TYPE:
                msg = deserialize_message(raw, self._diag_cls)
                self.monitor.diagnostics([
                    (s.name, int.from_bytes(s.level, "little") if isinstance(s.level, bytes) else int(s.level),
                     s.message, {kv.key: kv.value for kv in s.values})
                    for s in msg.status])
        except Exception:  # a malformed message must not take the bridge down
            logger.exception("Could not read %s", name)


class RosRuntime:
    """Owns rclpy init/shutdown and the background spin thread."""

    def __init__(self, cfg: Config, monitor: Monitor):
        rclpy.init()
        self.node = StyriBridgeNode(cfg, monitor)
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self.node)
        self._thread = threading.Thread(target=self._spin, name="ros-spin", daemon=True)

    def _spin(self) -> None:
        try:
            self._executor.spin()
        except ExternalShutdownException:
            pass

    def start(self) -> None:
        self._thread.start()

    def shutdown(self) -> None:
        self._executor.shutdown()
        self.node.destroy_node()
        rclpy.try_shutdown()
        self._thread.join(timeout=2)
