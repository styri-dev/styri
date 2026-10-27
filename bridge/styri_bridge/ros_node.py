"""ROS 2 side of the bridge. Only this module imports rclpy.

Read-only by construction: the node subscribes and never publishes. It
also turns off what rclpy creates by default (the /rosout logger, the
/parameter_events publisher and the parameter services), so the robot's
graph shows Styri with zero publishers and zero services.
"""

from __future__ import annotations

import logging
import os
import threading

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.convert import message_to_yaml
from rosidl_runtime_py.utilities import get_message

from .config import Config
from .monitor import Monitor

logger = logging.getLogger("styri_bridge")

NODE_NAME = "styri_bridge"
DISCOVERY_PERIOD = 2.0  # seconds
MAX_TOPICS = 300  # a safety cap for very large graphs


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
    def __init__(self, cfg: Config, monitor: Monitor, name: str = NODE_NAME, context=None):
        super().__init__(name, context=context, enable_rosout=False, start_parameter_services=False,
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
        # Latched topics (an action's status, a map) publish only on change and
        # keep their last message for late joiners; that takes a reliable,
        # transient-local subscription. Used only for mapped topics whose every
        # publisher is latched, so Styri sees the current value on start.
        self._latched = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                   history=HistoryPolicy.KEEP_LAST, depth=1)
        self._subs = {}
        self._classes = {}
        # Only mapped topics are decoded; everything else is just counted.
        self._mapped = monitor.mapped_topics()
        # A namespace (e.g. /amr2) to keep to, when several robots share a ROS
        # domain: then only its topics and the mapped ones are discovered.
        self.scope: str | None = None
        self.create_timer(DISCOVERY_PERIOD, self._discover)
        domain = monitor.robot.domain_id if monitor.robot.domain_id is not None \
            else os.environ.get("ROS_DOMAIN_ID", "0")
        logger.info("ROS 2 node online (ROS_DOMAIN_ID=%s, RMW=%s)", domain,
                    os.environ.get("RMW_IMPLEMENTATION", "default"))

    def _discover(self) -> None:
        scope = self.scope.rstrip("/") + "/" if self.scope else None
        # Hidden topics (an action's _action/status) only when mapped.
        graph = [(name, types[0]) for name, types in self.get_topic_names_and_types()
                 if types and (name in self._mapped or not _hidden(name))
                 and (scope is None or name.startswith(scope) or name in self._mapped)][:MAX_TOPICS]
        types = dict(graph)
        for name in self.monitor.discovered(graph, lambda t: _message_class(t) is not None):
            cls = _message_class(types[name])
            if cls is None:
                logger.info("Topic %s has type %s, which is not installed here", name, types[name])
                continue
            self._classes[name] = cls
            self._subs[name] = self.create_subscription(
                cls, name, lambda raw, n=name, t=types[name]: self._on_raw(n, t, raw), self._qos_for(name), raw=True)

    def _qos_for(self, name: str) -> QoSProfile:
        if name in self._mapped:
            pubs = self.get_publishers_info_by_topic(name)
            if pubs and all(p.qos_profile.durability == DurabilityPolicy.TRANSIENT_LOCAL
                            and p.qos_profile.reliability == ReliabilityPolicy.RELIABLE for p in pubs):
                return self._latched
        return self._qos

    def _on_raw(self, name: str, type_name: str, raw: bytes) -> None:
        self.monitor.message(name, raw)
        if name not in self._mapped:
            return
        try:
            self.monitor.mapped(name, deserialize_message(raw, self._classes[name]))
        except Exception:  # a malformed message must not take the bridge down
            logger.exception("Could not read %s", name)


class RosRuntime:
    """Owns one rclpy context (one ROS domain), its node and a spin thread."""

    def __init__(self, cfg: Config, monitor: Monitor, name: str = NODE_NAME):
        # A domain_id in the mapping file wins over ROS_DOMAIN_ID.
        self.context = rclpy.Context()
        rclpy.init(context=self.context, domain_id=monitor.robot.domain_id)
        self.node = StyriBridgeNode(cfg, monitor, name, context=self.context)
        self._executor = SingleThreadedExecutor(context=self.context)
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
        rclpy.try_shutdown(context=self.context)
        self._thread.join(timeout=2)
