"""VDA 5050 vehicles, over MQTT, into the unified robot model.

One asyncio task beside the rclpy bridge. It subscribes to every vehicle on the
broker, feeds the configured ones' monitors and `Live`, and notes the others
for `styri check`. With control off it has no way to publish: `send` refuses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import aiomqtt

from ..mapping import Settings
from ..model import RobotView
from ..sitemap import Graph, to_site
from . import orders, schema

logger = logging.getLogger("styri_bridge")

SUBSCRIBE = ("connection", "state", "visualization", "factsheet")
TOPIC_TYPES = {t: f"vda5050/{t}" for t in SUBSCRIBE}
RECONNECT_AFTER = 2.0  # seconds
REPORT_AFTER = 5       # failed tries before saying so, when it was never connected
STOP_RETRY = 1.0       # seconds between Operator stop retries, until the vehicle stands still
STOP_GIVE_UP = 15.0    # seconds, then the panel says it isn't confirmed
FACTSHEET_RETRY = 10.0  # seconds
MAX_JOIN = 2.0  # metres: further than this from a node, and not on an edge, an order won't start
ON_EDGE = 0.5  # metres
DEFAULT_VERSION = "2.1.0"
NOT_A_FAULT = {"noOrderToCancel"}  # what a vehicle reports when Operator stop finds no order


class VdaError(RuntimeError):
    """A command can't be sent. The message is for the operator."""


@dataclass
class Vehicle:
    view: RobotView
    headers: dict = field(default_factory=dict)  # topic -> last headerId
    version: str = DEFAULT_VERSION
    orders_sent: int = 0
    invalid_seen: set = field(default_factory=set)
    cancelled: str | None = None  # the order Styri cancelled: a cleared order then means idle, not done
    stop_until: float = 0.0
    state: dict | None = None
    next_factsheet_request: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        link = self.view.map.link
        return link.manufacturer, link.serial


class VdaClient:
    def __init__(self, views: list[RobotView], settings: Settings, activity, graph: Graph | None = None,
                 control: bool = False, env: dict | None = None):
        self.settings, self.activity, self.graph, self.control = settings, activity, graph, control
        self.env = os.environ if env is None else env
        self.vehicles = {v.key: v for v in (Vehicle(view) for view in views if view.map.link.protocol == "vda5050")}
        self.unconfigured: dict[tuple[str, str], float] = {}  # seen on the broker, not in styri.yaml
        self.mqtt: aiomqtt.Client | None = None
        self.connected = False
        self.seen_broker = False
        self.on_sent = None  # test hook: (topic, message)
        for v in self.vehicles.values():
            v.view.live.online = False
            v.view.monitor.discovered(list(TOPIC_TYPES.items()), lambda _t: True)

    # ---- connection -----------------------------------------------------

    def _client_args(self) -> dict:
        b = self.settings.broker
        if not b.url:
            return {"hostname": "127.0.0.1", "port": b.port}
        url = urlsplit(b.url)
        tls = url.scheme == "mqtts"
        args: dict = {"hostname": url.hostname, "port": url.port or (8883 if tls else 1883)}
        if tls:
            args["tls_context"] = ssl.create_default_context()
        if b.username:
            args.update(username=b.username, password=self.env.get(b.password_env or ""))
        return args

    async def run(self) -> None:
        """Stay connected. A broker that goes away, or never comes, is reported once, and retried."""
        failures = 0
        while True:
            try:
                async with aiomqtt.Client(identifier=f"styri-{os.getpid()}", **self._client_args()) as client:
                    self.mqtt, self.connected, failures = client, True, 0
                    self.seen_broker = True
                    self.activity.add("connection", "Connected to the MQTT broker", "vda")
                    await client.subscribe(f"{self.settings.interface}/+/+/+/+")
                    async for message in client.messages:
                        self.on_message(str(message.topic), message.payload)
                        await self._request_factsheets()
            except aiomqtt.MqttError as exc:
                self.mqtt = None
                failures += 1
                if self.connected:
                    logger.warning("MQTT broker: %s", exc)
                    self.activity.add("warning", "Lost the MQTT broker: VDA 5050 robots are stale until it's back", "vda")
                elif failures == REPORT_AFTER:  # the bundled broker takes a moment at start
                    logger.warning("MQTT broker: %s", exc)
                    self.activity.add("warning", "Can't reach the MQTT broker: VDA 5050 robots are stale until it's up", "vda")
                self.connected = False
                for v in self.vehicles.values():
                    v.view.live.online = False
                await asyncio.sleep(RECONNECT_AFTER)

    async def _request_factsheets(self) -> None:
        """Retained factsheets arrive by themselves; ask the vehicles that are up without one, if we may send."""
        if not self.control:
            return
        now = time.monotonic()
        for v in self.vehicles.values():
            if v.view.live.factsheet is None and v.view.live.online and now >= v.next_factsheet_request \
                    and "factsheetRequest" in v.view.map.link.instant_actions:
                v.next_factsheet_request = now + FACTSHEET_RETRY
                try:
                    await self._instant(v, "factsheetRequest")
                except VdaError as exc:
                    logger.info("No factsheet request for %s: %s", v.view.name, exc)

    # ---- incoming ---------------------------------------------------------

    def on_message(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")
        if len(parts) != 5 or parts[0] != self.settings.interface or parts[4] not in SUBSCRIBE:
            return
        key, kind = (parts[2], parts[3]), parts[4]
        vehicle = self.vehicles.get(key)
        if vehicle is None:
            self.unconfigured[key] = time.monotonic()
            return
        try:
            message = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._invalid(vehicle, kind, ["not JSON"])
            return
        wrong = schema.problems(kind, message)
        if wrong:
            self._invalid(vehicle, kind, wrong)
            if not isinstance(message, dict):
                return
        else:
            vehicle.invalid_seen.discard(kind)
            self._warnings(vehicle)
        monitor = vehicle.view.monitor
        monitor.message(kind, message)
        # Speak the vehicle's version, from its very first message.
        if isinstance(message.get("version"), str):
            vehicle.version = message["version"]
        try:
            if kind == "state":
                self._on_state(vehicle, message)
            elif kind == "connection":
                self._on_connection(vehicle, message)
            elif kind == "visualization":
                self._on_visualization(vehicle, message)
            elif kind == "factsheet":
                vehicle.view.live.factsheet = message
                self._warnings(vehicle)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:  # invalid, and already flagged
            logger.info("Could not read %s from %s: %s", kind, vehicle.view.name, exc)

    def _invalid(self, v: Vehicle, kind: str, wrong: list[str]) -> None:
        if kind not in v.invalid_seen:
            v.invalid_seen.add(kind)
            logger.warning("%s: invalid %s: %s", v.view.name, kind, "; ".join(wrong))
            v.view.monitor.activity.add("warning", f"Invalid {kind} message: {wrong[0]}", "vda")
        self._warnings(v)

    def _warnings(self, v: Vehicle) -> None:
        live = v.view.live
        out = [f"Invalid {kind} messages from this robot" for kind in sorted(v.invalid_seen)]
        if live.factsheet is not None:
            listed = {a.get("actionType") for a in live.factsheet.get("protocolFeatures", {}).get("agvActions", [])
                      if isinstance(a, dict)}
            if listed and "startPause" not in listed:
                out.append("This robot doesn't list startPause: Operator stop may let it drive on to its next node")
        if v.state is not None and self._cancel_held(v):
            out.append("Held, cancel pending")
        live.warnings = out

    @staticmethod
    def _cancel_held(v: Vehicle) -> bool:
        return bool(v.state.get("paused")) and any(
            a.get("actionType") == "cancelOrder" and a.get("actionStatus") in ("RUNNING", "INITIALIZING", "WAITING")
            for a in v.state.get("actionStates", ()))

    def _on_connection(self, v: Vehicle, msg: dict) -> None:
        online = msg.get("connectionState") == "ONLINE"
        if online != v.view.live.online:
            v.view.monitor.activity.add("connection", "Online" if online else f"Offline ({msg.get('connectionState')})",
                                        "vda")
        v.view.live.online = online

    def _on_state(self, v: Vehicle, msg: dict) -> None:
        live, monitor = v.view.live, v.view.monitor
        v.state = msg
        # Some vehicles send no connection topic; a state message says they're there.
        if live.online is False and v.view.monitor.topics["connection"].last is None:
            live.online = True
        monitor.mapped("state", msg)
        position = msg.get("agvPosition")
        if position:
            live.pose = {"x": position["x"], "y": position["y"], "theta": position["theta"], "map_id": position["mapId"]}
        velocity = msg.get("velocity")
        if velocity:
            live.velocity = {"linear": velocity.get("vx", 0.0), "angular": velocity.get("omega", 0.0)}
        live.driving, live.paused = msg.get("driving"), bool(msg.get("paused"))
        live.last_node = msg.get("lastNodeId") or None
        live.route = [n["nodeId"] for n in msg.get("nodeStates", ())]
        errors = [e for e in msg.get("errors", ()) if e.get("errorType") not in NOT_A_FAULT]
        live.errors = [{"type": e.get("errorType"), "level": e.get("errorLevel"),
                        "description": e.get("errorDescription", "")} for e in errors]
        faults = {e.get("errorType", "error"): (2 if e.get("errorLevel") == "FATAL" else 1,
                                                e.get("errorDescription") or e.get("errorLevel", "")) for e in errors}
        safety = msg.get("safetyState", {})
        live.vehicle_stop = safety.get("eStop", "NONE") != "NONE"  # the schema's own field name
        if live.vehicle_stop:
            faults["Vehicle safety stop"] = (2, "active")
        monitor.faults(faults)
        order = msg.get("orderId") or None
        running = bool(msg.get("nodeStates") or msg.get("edgeStates"))
        live.task_id = order
        if any(e.get("errorLevel") == "FATAL" for e in errors) and order:
            live.task_state = "failed"
        elif running:
            live.task_state = "paused" if live.paused else "active"
        else:
            live.task_state = "done" if order and order != v.cancelled else "idle"
        self._warnings(v)

    def _on_visualization(self, v: Vehicle, msg: dict) -> None:
        position = msg.get("agvPosition")
        if position:
            v.view.live.pose = {"x": position["x"], "y": position["y"], "theta": position["theta"],
                                "map_id": position["mapId"]}

    # ---- outgoing --------------------------------------------------------

    async def send(self, v: Vehicle, topic: str, body: dict) -> dict:
        """Publish one message, if it's valid. Raises VdaError otherwise."""
        if not self.control:
            raise VdaError("control is off")
        if self.mqtt is None:
            raise VdaError("not connected to the MQTT broker")
        link = v.view.map.link
        header = v.headers.get(topic, -1) + 1
        message = {"headerId": header, "timestamp": orders.timestamp(), "version": v.version,
                   "manufacturer": link.manufacturer, "serialNumber": link.serial, **body}
        wrong = schema.problems(topic, message)
        if wrong:
            # Never published. A bug here is ours, so say what's wrong in the log.
            logger.error("Refused to publish an invalid %s: %s", topic, "; ".join(wrong))
            raise VdaError(f"invalid {topic} message: {wrong[0]}")
        v.headers[topic] = header
        major = "v" + v.version.split(".")[0]
        await self.mqtt.publish(f"{self.settings.interface}/{major}/{link.manufacturer}/{link.serial}/{topic}",
                                json.dumps(message), qos=0)
        if self.on_sent:
            self.on_sent(topic, message)
        return message

    def _allowed(self, v: Vehicle, *types: str) -> None:
        for t in types:
            if t not in v.view.map.link.instant_actions:
                raise VdaError(f"{t} is not in this robot's instant_actions")

    async def _instant(self, v: Vehicle, *types: str) -> dict:
        self._allowed(v, *types)
        return await self.send(v, "instantActions", orders.instant(*types))

    def vehicle(self, view: RobotView) -> Vehicle:
        return self.vehicles[(view.map.link.manufacturer, view.map.link.serial)]

    async def pause(self, view: RobotView) -> dict:
        return await self._instant(self.vehicle(view), "startPause")

    async def resume(self, view: RobotView) -> dict:
        return await self._instant(self.vehicle(view), "stopPause")

    async def cancel(self, view: RobotView) -> dict:
        v = self.vehicle(view)
        v.cancelled = view.live.task_id
        return await self._instant(v, "cancelOrder")

    async def goal(self, view: RobotView, node_id: str | None = None, x: float | None = None,
                   y: float | None = None) -> dict:
        """Send the robot along the graph to a node, or to the node nearest a point on the site map."""
        v = self.vehicle(view)
        if self.graph is None:
            raise VdaError("no node graph: set site.graph in styri.yaml")
        if view.live.task_state in ("active", "paused"):
            raise VdaError("this robot already has an order: cancel it first")
        goal = self.graph.nodes.get(node_id) if node_id else self.graph.nearest(x, y)
        if goal is None:
            raise VdaError(f"no node {node_id} in the graph" if node_id else "the graph has no nodes")
        offset = view.map.link.map_offset
        pose = to_site(view.live.pose, offset)
        # After a stop a vehicle may stand partway along an edge, so its last node can be
        # behind it. An order has to start where it is: at the nearest node, with that
        # node's deviation wide enough to take it in.
        start = self.graph.nearest(pose["x"], pose["y"], pose.get("map_id")) if pose else None
        if start is None and pose is not None:
            start = self.graph.nearest(pose["x"], pose["y"])
        if start is None:
            start = self.graph.nodes.get(view.live.last_node or "")
        if start is None:
            raise VdaError("this robot's position isn't known yet")
        off_by = math.hypot(pose["x"] - start.x, pose["y"] - start.y) if pose else 0.0
        # Stopped on an edge is on the graph, however long the edge. Off it, only near a node.
        if off_by > MAX_JOIN and pose and self.graph.off_edges(pose["x"], pose["y"]) > ON_EDGE:
            raise VdaError(f"this robot is {off_by:.1f} m from the nearest node, {start.id}: move it nearer the graph")
        route = self.graph.route(start.id, goal.id)
        if route is None:
            raise VdaError(f"no route from {start.id} to {goal.id}")
        v.orders_sent += 1
        order_id = f"styri-{int(time.time())}-{v.orders_sent}"
        return await self.send(v, "order", orders.order(order_id, *route, offset, start_deviation=off_by * 1.1 + 0.1))

    async def operator_stop(self, view: RobotView) -> dict:
        """startPause then cancelOrder in one message, repeated until the vehicle stands still.

        Stopped means `driving: false`. The cancel may stay RUNNING while paused,
        so it's never waited for, and Styri never sends stopPause by itself:
        that can set the vehicle moving again.
        """
        v = self.vehicle(view)
        v.cancelled = view.live.task_id
        types = [t for t in ("startPause", "cancelOrder") if t in view.map.link.instant_actions]
        if not types:
            raise VdaError("neither startPause nor cancelOrder is in this robot's instant_actions")
        sent = await self.send(v, "instantActions", orders.instant(*types))
        if time.monotonic() > v.stop_until:
            v.stop_until = time.monotonic() + STOP_GIVE_UP
            asyncio.get_running_loop().create_task(self._until_stopped(v, types))
        return sent

    async def _until_stopped(self, v: Vehicle, types: list[str]) -> None:
        while time.monotonic() < v.stop_until:
            await asyncio.sleep(STOP_RETRY)
            if v.view.live.driving is False:
                return
            try:
                await self.send(v, "instantActions", orders.instant(*types))
            except VdaError as exc:
                logger.warning("Operator stop retry for %s: %s", v.view.name, exc)
        v.view.monitor.activity.add("warning", "Operator stop not confirmed: the robot still reports driving", "vda")
