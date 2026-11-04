"""Control, attached to the bridge only when it's turned on.

Every command takes the same path: login, then parse, then the whitelist
(what the robot's styri.yaml entry allows), then the sink. Whatever happens,
the audit log gets a line, in the same order.

Operator stop is a software stop. It is not an emergency stop or a safety function.
"""

from __future__ import annotations

import asyncio
import json
import logging
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..model import RobotView, capabilities, is_stale
from ..server import BridgeServer, Session, peer_ip
from . import commands
from .auth import ADMIN, Admin, token_from
from .commands import CommandError
from .sinks import LogSink, RosSink
from .teleop import Teleop

logger = logging.getLogger("styri_bridge")

STALE = "This robot's data is stale: teleop and waypoints are off. Operator stop stays available."
OTHER_DRIVER = "Being driven by another session"
AUDIT_ROWS = 200


class Refused(Exception):
    """A command that won't be sent. The message is for the operator."""


class Control:
    def __init__(self, bridge: BridgeServer, admin: Admin | None = None, sinks: dict | None = None, vda=None):
        self.bridge = bridge
        self.audit = bridge.audit
        settings = bridge.cfg.mapping.settings
        self.admin = admin or Admin(str(Path(bridge.cfg.audit_db).parent / "admin.hash")
                                    if bridge.cfg.audit_db != ":memory:" else None, settings.session_hours)
        self.teleop = Teleop()
        self.sinks: dict[int, object] = dict(sinks or {})
        self.vda = vda
        self.stopping: set[int] = set()  # robots in their Operator stop: no teleop until it's over

    def attach(self) -> "Control":
        b = self.bridge
        for action in commands.ROBOT_COMMANDS:
            b.actions[action] = lambda s, d, a=action: self._robot_command(s, a, d)
        b.actions["OPERATOR_STOP_ALL"] = self._stop_all
        b.actions["LOGIN"] = self._login
        b.actions["SETUP"] = self._setup
        b.actions["LOGOUT"] = self._logout
        b.actions["AUDIT"] = self._audit_rows
        b.routes["/api/session"] = self._set_cookie
        b.routes["/api/logout"] = self._clear_cookie
        b.routes["/audit.jsonl"] = self._export
        b.hello_session.append(self._hello)
        b.on_disconnect.append(self.teleop.disconnected)
        b.on_ros_node.append(self._ros_node)
        b.on_shutdown.append(self.teleop.stop)
        b.background.append(self._start_watchdog)
        return self

    async def _start_watchdog(self) -> None:
        self.teleop.start()

    def _ros_node(self, view: RobotView, node) -> None:
        self.sinks[view.index] = RosSink(node, view.map)

    def _sink(self, view: RobotView):
        if view.map.link.protocol == "vda5050":
            if self.vda is None:
                raise Refused("VDA 5050 isn't running")
            return self.vda
        return self.sinks.setdefault(view.index, LogSink(view.map))

    # ---- who's asking -----------------------------------------------------

    def _hello(self, session: Session) -> dict:
        request = session.ws.request
        token = token_from(request.headers.get("Cookie")) if request else None
        logged_in = self.admin.valid(token)
        if logged_in:
            session.data["token"] = token
        return {"control": self._status(session)}

    def _status(self, session: Session) -> dict:
        return {"enabled": True, "logged_in": self._logged_in(session), "needs_setup": self.admin.needs_setup,
                "session_hours": self.admin.lifetime / 3600}

    def _logged_in(self, session: Session) -> bool:
        return self.admin.valid(session.data.get("token"), touch=False)

    @staticmethod
    def _user(logged_in: bool) -> str | None:
        return ADMIN if logged_in else None

    def _reject(self, session: Session, command: str, reason: str, robot: str | None = None, payload=None) -> dict:
        self.audit.record("command_rejected", client=session.client, user=self._user(self._logged_in(session)),
                          action=command, robot=robot, payload=payload, reason=reason)
        return {"type": "error", "action": command, "robot": robot, "error": reason}

    # ---- login -------------------------------------------------------------

    async def _login(self, session: Session, data: dict) -> dict:
        client = session.client
        wait = self.admin.locked(client)
        if wait > 0:
            self.audit.record("login_throttled", client=client, user=ADMIN)
            return {"type": "auth", "error": f"Too many attempts. Try again in {int(wait) + 1} s.", "control": self._status(session)}
        password = data.get("password")
        # scrypt is slow on purpose: off the event loop.
        ok = isinstance(password, str) and await asyncio.to_thread(self.admin.check, client, password)
        if not ok:
            self.audit.record("login_failed", client=client, user=ADMIN)
            return {"type": "auth", "error": "Wrong password.", "control": self._status(session)}
        return self._open(session)

    def _open(self, session: Session) -> dict:
        token, ticket = self.admin.open_session()
        session.data["token"] = token
        self.audit.record("login", client=session.client, user=ADMIN)
        return {"type": "auth", "ticket": ticket, "control": self._status(session)}

    async def _setup(self, session: Session, data: dict) -> dict:
        password = data.get("password")
        try:
            if not isinstance(password, str):
                raise ValueError("enter a password")
            await asyncio.to_thread(self.admin.setup, password)
        except ValueError as exc:
            return {"type": "auth", "error": str(exc).capitalize() + ".", "control": self._status(session)}
        self.audit.record("admin_password_set", client=session.client, user=ADMIN)
        return self._open(session)

    async def _logout(self, session: Session, data: dict) -> dict:
        self.teleop.disconnected(session)
        self.admin.close_session(session.data.pop("token", None))
        self.audit.record("logout", client=session.client, user=ADMIN)
        return {"type": "auth", "control": self._status(session)}

    def _set_cookie(self, connection, request):
        query = parse_qs(urlsplit(request.path).query)
        token = self.admin.redeem(query.get("ticket", [""])[0])
        if token is None:
            return connection.respond(HTTPStatus.UNAUTHORIZED, "ticket not valid\n")
        response = connection.respond(HTTPStatus.OK, "ok\n")
        response.headers["Set-Cookie"] = self.admin.cookie(token)
        response.headers["Cache-Control"] = "no-store"
        return response

    def _clear_cookie(self, connection, request):
        self.admin.close_session(token_from(request.headers.get("Cookie")))
        response = connection.respond(HTTPStatus.OK, "ok\n")
        response.headers["Set-Cookie"] = self.admin.clear_cookie()
        return response

    # ---- the audit log ------------------------------------------------------

    async def _audit_rows(self, session: Session, data: dict) -> dict:
        if not self._logged_in(session):
            return {"type": "error", "action": "AUDIT", "error": "Log in to see the audit log."}
        robot = data.get("robot") if isinstance(data.get("robot"), str) else None
        return {"type": "audit", "robot": robot, "rows": self.audit.commands(robot, AUDIT_ROWS)}

    def _export(self, connection, request):
        client = peer_ip(connection, request)
        if not self.admin.valid(token_from(request.headers.get("Cookie"))):
            self.audit.record("auth_rejected", client=client, path="/audit.jsonl")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "log in first\n")
        self.audit.record("audit_export", client=client, user=ADMIN)
        body = "".join(json.dumps(row) + "\n" for row in self.audit.commands())
        response = connection.respond(HTTPStatus.OK, body)
        del response.headers["Content-Type"]
        response.headers["Content-Type"] = "application/x-ndjson"
        response.headers["Content-Disposition"] = 'attachment; filename="styri-audit.jsonl"'
        response.headers["Cache-Control"] = "no-store"
        return response

    # ---- commands -------------------------------------------------------------

    def _view(self, data: dict) -> RobotView:
        wanted = data.get("robot")
        for view in self.bridge.robots:
            if view.id == wanted or (type(wanted) is int and view.index == wanted):
                return view
        raise Refused(f"no robot {str(wanted)[:64]!r} on this panel")

    def _stale(self, view: RobotView) -> bool:
        snap = self.bridge._snapshots.get(view.index) or self.bridge.snapshot(view.index)
        return is_stale(view, snap)

    def _allow(self, view: RobotView, action: str) -> None:
        """The whitelist: what this robot's styri.yaml entry allows."""
        caps = capabilities(view.map, view.live)
        need = {"TELEOP": "can_teleop", "TELEOP_RELEASE": "can_teleop", "GOAL": "can_waypoint", "PAUSE": "can_pause",
                "RESUME": "can_pause", "CANCEL": "can_cancel", "OPERATOR_STOP": "can_stop"}[action]
        if not caps[need]:
            raise Refused(f"{action} isn't allowed for this robot: see its entry in styri.yaml")
        if action in ("TELEOP", "GOAL") and self._stale(view):
            raise Refused(STALE)

    async def _robot_command(self, session: Session, action: str, data: dict) -> dict | None:
        payload = {k: v for k, v in data.items() if k not in ("action", "robot", "id")}
        robot = data.get("robot") if isinstance(data.get("robot"), str) else None
        if not self.admin.valid(session.data.get("token")):
            return self._reject(session, action, "Log in to control robots.", robot, payload)
        try:
            view = self._view(data)
            robot = view.id
            self._allow(view, action)
            if action == "TELEOP":
                return self._drive(session, view, data, payload)
            if action == "TELEOP_RELEASE":
                self.teleop.release(view.index, "released", session)
                return None
            sent = await self._send(view, action, data)
        except CommandError as exc:
            return self._reject(session, action, str(exc), robot, payload)
        except Refused as exc:
            return self._reject(session, action, str(exc), robot, payload)
        except RuntimeError as exc:  # SinkError, VdaError: couldn't be carried out
            return self._reject(session, action, str(exc), robot, payload)
        self.audit.record("command", client=session.client, user=ADMIN, action=action, robot=robot,
                          payload={**payload, **sent})
        if action == "OPERATOR_STOP":
            view.monitor.activity.add("warning", f"Operator stop from {session.client}", "control")
        return {"type": "ack", "action": action, "robot": robot, "id": data.get("id")}

    async def _send(self, view: RobotView, action: str, data: dict) -> dict:
        sink = self._sink(view)
        if action == "GOAL":
            return await self._goal(view, sink, commands.goal(data))
        if action == "PAUSE":
            await sink.pause(view)
        elif action == "RESUME":
            await sink.resume(view)
        elif action == "CANCEL":
            await sink.cancel(view)
        elif action == "OPERATOR_STOP":
            await self._operator_stop(view, sink)
        return {}

    async def _goal(self, view: RobotView, sink, goal: commands.Goal) -> dict:
        link = view.map.link
        if goal.point is not None:
            found = next((p for p in link.points if p[0] == goal.point), None)
            if found is None:
                raise Refused(f"no saved point {goal.point!r} for this robot")
            goal = commands.Goal(x=found[1], y=found[2], theta=found[3])
        if link.protocol == "vda5050":
            sent = await sink.goal(view, node_id=goal.node, x=goal.x, y=goal.y)
            return {"order_id": sent["orderId"], "nodes": [n["nodeId"] for n in sent["nodes"]]}
        if goal.x is None:
            raise Refused("this robot takes a point on the map, not a graph node")
        await sink.goal(view, goal.x, goal.y, goal.theta)
        return {}

    async def _operator_stop(self, view: RobotView, sink) -> None:
        self.stopping.add(view.index)
        asyncio.get_running_loop().call_later(2.0, self.stopping.discard, view.index)
        self.teleop.release(view.index, "operator_stop")
        await sink.operator_stop(view)

    def _drive(self, session: Session, view: RobotView, data: dict, payload: dict) -> dict | None:
        if view.index in self.stopping:
            raise Refused("Operator stop in progress")
        link = view.map.link
        linear = commands.clamp(commands.number(data, "linear"), link.max_linear)
        angular = commands.clamp(commands.number(data, "angular"), link.max_angular)
        sink = self._sink(view)
        started = self.teleop.driver(view.index) is None
        if not self.teleop.drive(view.index, session, linear, angular, sink.velocity,
                                 lambda reason: self._drive_ended(session, view, reason)):
            raise Refused(OTHER_DRIVER)
        if started:
            self.audit.record("command", client=session.client, user=ADMIN, action="TELEOP", robot=view.id,
                              payload={"event": "start", "limits": [link.max_linear, link.max_angular]})
        return None  # streams at 10-20 Hz: no reply per message

    def _drive_ended(self, session: Session, view: RobotView, reason: str) -> None:
        self.audit.record("command", client=session.client, user=ADMIN, action="TELEOP", robot=view.id,
                          payload={"event": "stop", "reason": reason})

    async def _stop_all(self, session: Session, data: dict) -> dict:
        if not self.admin.valid(session.data.get("token")):
            return self._reject(session, "OPERATOR_STOP_ALL", "Log in to control robots.")
        results = await asyncio.gather(*(self._robot_command(session, "OPERATOR_STOP", {"robot": v.id})
                                         for v in self.bridge.robots if capabilities(v.map, v.live)["can_stop"]))
        failed = [r["robot"] for r in results if r and r["type"] == "error"]
        self.audit.record("command", client=session.client, user=ADMIN, action="OPERATOR_STOP_ALL", failed=failed)
        return {"type": "ack", "action": "OPERATOR_STOP_ALL", "failed": failed, "id": data.get("id")}
