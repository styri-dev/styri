"""The one server Styri runs: operator UI, live data and a probe on one port.

  GET  /           the operator UI (static files from the Vite build)
  WS   /ws         snapshots, activity log, topic inspection
  GET  /healthz    liveness probe

Styri Core is read-only. Browsers can ask for data (PING, SELECT) and
nothing else; the bridge never publishes to the robot.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from . import __version__, protocol
from .audit import Activity, AuditLog
from .config import Config
from .monitor import Monitor
from .static import StaticFiles

logger = logging.getLogger("styri_bridge")

SNAPSHOT_PERIOD = 1.0  # seconds
MAX_PREVIEW = 8000  # characters of a message shown on the Topics tab
READ_ONLY = "Styri Core is read-only: it never sends anything to the robot."


def _format_plain(value, indent: int = 0) -> str:
    """YAML-ish text for dict payloads (the fake robot); ROS messages use rosidl."""
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}:\n{_format_plain(v, indent + 1)}")
            else:
                lines.append(f"{pad}{k}: {v}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(f"{pad}- {_format_plain(v, 0) if isinstance(v, (dict, list)) else v}" for v in value)
    return f"{pad}{value}"


def peer_ip(connection: ServerConnection, request: Request | None = None) -> str:
    """Client IP. Trusts X-Forwarded-For only from a loopback peer (a local reverse proxy)."""
    addr = connection.remote_address
    ip = addr[0] if addr else "unknown"
    request = request or connection.request
    try:
        loopback = ipaddress.ip_address(ip).is_loopback
    except ValueError:
        loopback = False
    if loopback and request is not None:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return ip


def _origin_ok(request: Request) -> bool:
    """Refuse cross-site WebSocket connections from other pages."""
    origin = request.headers.get("Origin")
    if origin is None:
        return True  # non-browser client
    return urlsplit(origin).netloc == request.headers.get("Host")


@dataclass
class Session:
    ws: ServerConnection
    client: str
    data: dict = field(default_factory=dict)  # per-connection state for extensions


Action = Callable[[Session, dict], Awaitable[dict | None]]
Route = Callable[[ServerConnection, Request], Response | None]


@dataclass
class RobotView:
    """One robot the panel shows. Styri Core has exactly one; extensions may add more."""
    index: int
    name: str
    domain: str
    monitor: Monitor


class _Tagged:
    """Activity from one of several robots: the robot's name goes in front."""

    def __init__(self, activity: Activity, name: str):
        self.activity, self.name = activity, name

    def add(self, kind: str, msg: str, source: str) -> None:
        self.activity.add(kind, f"{self.name} · {msg}", source)


class BridgeServer:
    def __init__(self, cfg: Config, audit: AuditLog):
        self.cfg = cfg
        self.audit = audit
        self.activity = Activity(audit, self.publish_threadsafe)
        self.monitor = Monitor(self.activity, cfg.robot)
        self.static = StaticFiles(cfg.ui_dir)
        # Turns (type name, last raw message) into text for the Topics tab.
        # The ROS node installs a rosidl-based one; dict payloads need none.
        self.decode = None
        self.domain = str(cfg.robot.domain_id) if cfg.robot.domain_id is not None \
            else os.environ.get("ROS_DOMAIN_ID", "0")
        self.robots: list[RobotView] = [RobotView(0, cfg.robot_name, self.domain, self.monitor)]
        self.clients: set[ServerConnection] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._snapshots: dict[int, dict] = {}
        # Extension points (see extensions.py). Empty in Styri Core.
        self.actions: dict[str, Action] = {}
        self.routes: dict[str, Route] = {}
        self.hello_extra: dict = {}
        self.on_connect: list[Callable[[Session], None]] = []
        self.on_disconnect: list[Callable[[Session], None]] = []
        self.on_ros_node: list[Callable[[object], None]] = []
        self.background: list[Callable[[], Awaitable[None]]] = []
        self.on_shutdown: list[Callable[[], None]] = []

    # ---- outbound (any thread) ----------------------------------------

    def publish_threadsafe(self, payload: dict) -> None:
        loop = self._loop
        if loop is None or not self.clients:
            return
        try:
            text = json.dumps(payload, allow_nan=False)
        except ValueError:
            logger.warning("Dropping non-JSON-safe payload of type %s", payload.get("type"))
            return
        loop.call_soon_threadsafe(self._broadcast, text)

    def _broadcast(self, text: str) -> None:
        # websockets.broadcast skips clients whose buffers are full rather than
        # blocking, so one slow tablet cannot stall the others.
        broadcast(self.clients, text)

    # ---- lifecycle ------------------------------------------------------

    async def run(self, stop: asyncio.Future) -> None:
        self._loop = asyncio.get_running_loop()
        async with serve(self._handler, self.cfg.host, self.cfg.port,
                         process_request=self._process_request, max_size=16 * 1024):
            logger.info("Styri v%s on http://%s:%d", __version__, self.cfg.host, self.cfg.port)
            if not self.static.available():
                logger.warning("No UI build at %s; only the WebSocket is served", self.cfg.ui_dir)
            self.activity.add("state", f"styri v{__version__} started", "styri-bridge")
            if self.cfg.mapping.error:
                logger.error("Configuration %s not used: %s", self.cfg.mapping.source, self.cfg.mapping.error)
                self.activity.add("warning", f"Configuration file not used: {self.cfg.mapping.error}",
                                  "configuration")
            else:
                logger.info("Topic mapping from %s", self.cfg.mapping.source)
            tasks = [asyncio.create_task(self._snapshots_loop())] + [asyncio.create_task(f()) for f in self.background]
            try:
                await stop
            finally:
                for task in tasks:
                    task.cancel()
                for hook in self.on_shutdown:
                    hook()

    def add_robot(self, robot) -> RobotView:
        """Show another robot (a mapping.RobotMap). Extensions feed its monitor."""
        if len(self.robots) == 1:
            self.monitor.activity = _Tagged(self.activity, self.robots[0].name)
        domain = str(robot.domain_id) if robot.domain_id is not None else os.environ.get("ROS_DOMAIN_ID", "0")
        view = RobotView(len(self.robots), robot.name, domain,
                         Monitor(_Tagged(self.activity, robot.name), robot))
        self.robots.append(view)
        return view

    def config_summary(self) -> dict:
        """Where the mapping came from, for the panel's Configuration view."""
        loaded, robot = self.cfg.mapping, self.cfg.robot
        notes = list(loaded.notes)
        if len(loaded.robots) > len(self.robots) == 1:
            notes.append(f"This file lists {len(loaded.robots)} robots. Styri Core shows the first, "
                         f"{robot.name}; Styri Pilot shows up to five.")
        elif len(loaded.robots) > len(self.robots):
            notes.append(f"This file lists {len(loaded.robots)} robots; the panel shows the first {len(self.robots)}.")
        return {"source": loaded.source, "error": loaded.error, "notes": notes,
                "robots_in_file": len(loaded.robots), "namespace": robot.namespace or None,
                "domain": self.domain, "stale_after": robot.stale_after, "host_fallback": robot.host_fallback}

    def snapshot(self, index: int = 0) -> dict:
        r = self.robots[index]
        snap = r.monitor.evaluate()
        snap.update(type="snapshot", robot=r.name, domain=r.domain, robot_index=r.index)
        self._snapshots[index] = snap
        return snap

    @property
    def _snapshot(self) -> dict | None:
        return self._snapshots.get(0)

    async def _snapshots_loop(self) -> None:
        while True:
            for r in self.robots:
                try:
                    self.publish_threadsafe(self.snapshot(r.index))
                except Exception:  # never let one bad reading stop the panel
                    logger.exception("snapshot failed for %s", r.name)
            await asyncio.sleep(SNAPSHOT_PERIOD)

    # ---- HTTP -----------------------------------------------------------

    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        path = urlsplit(request.path).path
        if path == "/healthz":
            return connection.respond(HTTPStatus.OK, "ok\n")
        if path in self.routes:
            return self.routes[path](connection, request)
        if path != "/ws":
            return self.static.response(path)
        if not _origin_ok(request):
            self.audit.record("origin_rejected", client=peer_ip(connection, request),
                              origin=request.headers.get("Origin"))
            return connection.respond(HTTPStatus.FORBIDDEN, "cross-origin connection refused\n")
        return None  # proceed with the WebSocket handshake

    # ---- WebSocket --------------------------------------------------------

    async def _handler(self, ws: ServerConnection) -> None:
        session = Session(ws, client=peer_ip(ws))
        hello = {"type": "hello", "version": __version__, "robot": self.cfg.robot_name,
                 "domain": self.domain, "stale_after": self.cfg.stale_after, "controls": False,
                 "min_voltage": self.cfg.min_voltage, "config": self.config_summary(),
                 "robots": [{"index": r.index, "name": r.name, "domain": r.domain,
                             "namespace": r.monitor.robot.namespace or None} for r in self.robots],
                 **self.hello_extra}
        await ws.send(json.dumps(hello))
        await ws.send(json.dumps({"type": "activity", "events": self.activity.recent()}))
        for snap in list(self._snapshots.values()):
            await ws.send(json.dumps(snap, allow_nan=False))
        # Join the broadcast only after the history, so no event is sent twice.
        self.clients.add(ws)
        for hook in self.on_connect:
            hook(session)
        self.activity.add("connection", f"Browser connected from {session.client}", "browser")
        try:
            async for message in ws:
                reply = await self._handle_message(session, message)
                if reply is not None:
                    await ws.send(json.dumps(reply))
        except ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)
            for hook in self.on_disconnect:
                hook(session)
            self.activity.add("connection", f"Browser disconnected · {session.client}", "browser")

    async def _handle_message(self, session: Session, message) -> dict | None:
        try:
            action, data = protocol.parse(message)
            if action == "PING":
                return {"type": "pong", "t": protocol.ping(data).t}
            if action == "SELECT":
                sel = protocol.select(data)
                return await self._select(sel.topic, sel.robot)
        except protocol.ProtocolError as exc:
            return {"type": "error", "error": str(exc)}
        if action in self.actions:
            return await self.actions[action](session, data)
        self.audit.record("command_rejected", client=session.client, action=action[:64], reason="read-only")
        return {"type": "error", "action": action[:64], "error": READ_ONLY}

    async def _select(self, topic: str, robot: int = 0) -> dict:
        if robot >= len(self.robots):
            return {"type": "message", "topic": topic, "robot_index": robot, "error": "unknown robot"}
        state, raw = self.robots[robot].monitor.latest(topic)
        if state is None:
            return {"type": "message", "topic": topic, "robot_index": robot, "error": "unknown topic"}
        reply = {"type": "message", "topic": topic, "robot_index": robot, "msg_type": state.type,
                 "text": None, "note": None}
        if not state.supported:
            reply["note"] = f"{state.type} is not installed in this image, so Styri can list it but not read it."
        elif raw is None:
            reply["note"] = "No messages received in this session."
        elif isinstance(raw, dict):
            reply["text"] = _format_plain(raw)
        elif self.decode is not None:
            try:
                reply["text"] = await asyncio.to_thread(self.decode, state.type, raw)
            except Exception as exc:
                reply["note"] = f"Could not decode: {exc}"
        if reply["text"] and len(reply["text"]) > MAX_PREVIEW:
            reply["text"] = reply["text"][:MAX_PREVIEW] + "\n# … truncated"
        return reply
