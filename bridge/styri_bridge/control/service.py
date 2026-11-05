"""Control, attached to the bridge only when it's turned on.

Every command takes the same path: login, then parse, then the whitelist
(what the robot's styri.yaml entry allows), then the sink. Whatever happens,
the audit log gets a line, in the same order.

Stopping is the safe direction, so with control on, whoever sees a problem can
stop a robot without logging in, unless `control.stop_requires_login` says no.
Anything that undoes a stop (resume, a new goal, teleop) always needs the login.

Operator stop is a software stop. It is not an emergency stop or a safety function.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from websockets.exceptions import ConnectionClosed

from ..model import Command, RobotView, advance, capabilities, is_stale, next_step, stop_over, stop_sent
from ..server import MAX_MESSAGE, MAX_MESSAGE_LOGGED_IN, BridgeServer, Session, peer_ip
from ..sitemap import Graph, GraphError
from . import commands
from .auth import ADMIN, ANONYMOUS, OPERATOR, AccountError, Accounts, Switches, User, token_from
from .commands import CommandError
from .sinks import LogSink, RosSink
from .teleop import Teleop

logger = logging.getLogger("styri_bridge")

PAUSED = "This robot is paused. Press Resume first."
GRAPH_CHANGED = "The graph changed since you opened it. Reload."
STALE = "This robot's data is stale: teleop and waypoints are off. Operator stop stays available."
OTHER_DRIVER = "Being driven by another session"
AUDIT_ROWS = 200
ANONYMOUS_STOP_EVERY = 2.0  # seconds per robot, for stops without a login
TRACKED = ("GOAL", "PAUSE", "RESUME", "CANCEL", "OPERATOR_STOP")  # the commands with steps to follow
SESSION_WARNING = 120.0  # seconds before a session ends that the panel says so
SESSION_CHECK = 5.0


class Refused(Exception):
    """A command that won't be sent. The message is for the operator."""


class Control:
    def __init__(self, bridge: BridgeServer, accounts: Accounts | None = None, sinks: dict | None = None, vda=None,
                 switches: Switches | None = None):
        self.bridge = bridge
        self.audit = bridge.audit
        settings = bridge.cfg.mapping.settings
        folder = None if bridge.cfg.audit_db == ":memory:" else Path(bridge.cfg.audit_db).parent
        self.accounts = accounts or Accounts(str(folder / "users.json") if folder else None, settings.session_hours)
        self.switches = switches or Switches(str(folder / "switches.json") if folder else None)
        self.teleop = Teleop()
        self.sinks: dict[int, object] = dict(sinks or {})
        self.vda = vda
        self.stopping: set[int] = set()  # robots in their Operator stop: no teleop until it's over
        self.stop_requires_login = settings.stop_requires_login
        self.clock = time.monotonic
        self._anonymous_stops: dict[int, float] = {}  # robot index -> last stop without a login
        self._drives: dict[int, float] = {}  # robot index -> when the drive started
        self._saving = asyncio.Lock()

    def attach(self) -> "Control":
        b = self.bridge
        for action in commands.ROBOT_COMMANDS:
            b.actions[action] = lambda s, d, a=action: self._robot_command(s, a, d)
        b.actions["OPERATOR_STOP_ALL"] = self._stop_all
        b.actions["LOGIN"] = self._login
        b.actions["SETUP"] = self._setup
        b.actions["LOGOUT"] = self._logout
        b.actions["SESSION_KEEP"] = self._session_keep
        b.actions["AUDIT"] = self._audit_rows
        b.actions["GRAPH_SAVE"] = self._graph_save
        for action, handler in (("USERS", self._users), ("USER_ADD", self._user_add), ("USER_REMOVE", self._user_remove),
                                ("USER_ROLE", self._user_role), ("USER_PASSWORD", self._user_password),
                                ("SWITCHES", self._set_switches)):
            b.actions[action] = lambda s, d, h=handler, a=action: self._admin_only(s, a, d, h)
        b.view_gate = lambda session: self.switches.anonymous_view or self._account(session) is not None
        b.http_gate = lambda request: self.switches.anonymous_view or \
            self.accounts.valid(token_from(request.headers.get("Cookie")))
        if self.vda is not None:
            self.vda.control = self.switches.control
        b.routes["/api/session"] = self._set_cookie
        b.routes["/api/logout"] = self._clear_cookie
        b.routes["/audit.jsonl"] = self._export
        b.hello_session.append(self._hello)
        b.on_disconnect.append(self.teleop.disconnected)
        b.on_ros_node.append(self._ros_node)
        b.on_shutdown.append(self.teleop.stop)
        b.on_fleet.append(self._follow_commands)
        b.background.append(self._start_watchdog)
        b.background.append(self._watch_sessions)
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
        if "token" not in session.data and self.accounts.valid(token):
            self._logged_in_now(session, token)
        return {"control": self._status(session)}

    @staticmethod
    def _logged_in_now(session: Session, token: str) -> None:
        session.data["token"] = token
        # Anonymous connections stay at the small limit: only a login may send a node graph.
        session.ws.protocol.max_message_size = MAX_MESSAGE_LOGGED_IN

    def _status(self, session: Session) -> dict:
        user = self._account(session)
        return {"enabled": self.switches.control, "available": True, "logged_in": user is not None,
                "user": {"name": user.name, "role": user.role} if user else None,
                "needs_setup": self.accounts.needs_setup, "session_hours": self.accounts.lifetime / 3600,
                "stop_requires_login": self.stop_requires_login, "anonymous_view": self.switches.anonymous_view}

    def _account(self, session: Session, touch: bool = False) -> User | None:
        return self.accounts.user(session.data.get("token"), touch=touch)

    def _user(self, session: Session) -> str:
        user = self._account(session)
        return user.name if user else ANONYMOUS

    @staticmethod
    def _agent(session: Session) -> str | None:
        request = session.ws.request
        return (request.headers.get("User-Agent") or "")[:200] or None if request else None

    def _reject(self, session: Session, command: str, reason: str, robot: str | None = None, payload=None,
                **extra) -> dict:
        self.audit.record("command_rejected", client=session.client, user=self._user(session), action=command,
                          robot=robot, payload=payload, reason=reason, user_agent=self._agent(session))
        return {"type": "error", "action": command, "robot": robot, "error": reason, **extra}

    # ---- login -------------------------------------------------------------

    async def _login(self, session: Session, data: dict) -> dict:
        client = session.client
        name = data.get("username") or ADMIN
        wait = self.accounts.locked(client)
        if wait > 0:
            self.audit.record("login_throttled", client=client, user=str(name)[:32])
            return {"type": "auth", "error": f"Too many attempts. Try again in {int(wait) + 1} s.", "control": self._status(session)}
        password = data.get("password")
        # scrypt is slow on purpose: off the event loop.
        user = await asyncio.to_thread(self.accounts.check, client, name, password) \
            if isinstance(password, str) and isinstance(name, str) else None
        if user is None:
            self.audit.record("login_failed", client=client, user=str(name)[:32])
            return {"type": "auth", "error": "Wrong username or password.", "control": self._status(session)}
        return await self._open(session, user.name)

    async def _open(self, session: Session, name: str) -> dict:
        token, ticket = self.accounts.open_session(name)
        self._logged_in_now(session, token)
        self.audit.record("login", client=session.client, user=name)
        await self.bridge.open_view(session)
        return {"type": "auth", "ticket": ticket, "control": self._status(session)}

    async def _setup(self, session: Session, data: dict) -> dict:
        try:
            await asyncio.to_thread(self.accounts.setup, data.get("password"))
        except AccountError as exc:
            return {"type": "auth", "error": str(exc).capitalize() + ".", "control": self._status(session)}
        self.audit.record("admin_password_set", client=session.client, user=ADMIN)
        return await self._open(session, ADMIN)

    async def _logout(self, session: Session, data: dict) -> dict:
        who = self._user(session)
        self.teleop.disconnected(session)
        self.accounts.close_session(session.data.pop("token", None))
        session.ws.protocol.max_message_size = MAX_MESSAGE
        self.audit.record("logout", client=session.client, user=who)
        if not self.switches.anonymous_view:
            await self.bridge.close_view(session)
        return {"type": "auth", "control": self._status(session)}

    async def _session_keep(self, session: Session, data: dict) -> dict:
        """Stay logged in: any use of a session keeps it alive."""
        session.data.pop("warned", None)
        self._account(session, touch=True)
        return {"type": "auth", "control": self._status(session)}

    async def _watch_sessions(self) -> None:
        while True:
            await asyncio.sleep(SESSION_CHECK)
            await self.session_notices()

    async def session_notices(self) -> None:
        """A session ends after inactivity. Say so first, and tell the panel when it has."""
        for session in list(self.bridge.sessions):
            token = session.data.get("token")
            if token is None:
                continue
            left = self.accounts.remaining(token)
            try:
                if left == 0:
                    session.data.pop("token")
                    session.data.pop("warned", None)
                    session.ws.protocol.max_message_size = MAX_MESSAGE
                    await session.ws.send(json.dumps({"type": "auth", "control": self._status(session)}))
                    if not self.switches.anonymous_view:
                        await self.bridge.close_view(session)
                elif left <= SESSION_WARNING:
                    session.data["warned"] = True
                    await session.ws.send(json.dumps({"type": "session", "ends_in": round(left)}))
                elif session.data.pop("warned", False):
                    await session.ws.send(json.dumps({"type": "session", "ends_in": None}))
            except ConnectionClosed:
                pass

    def _set_cookie(self, connection, request):
        query = parse_qs(urlsplit(request.path).query)
        token = self.accounts.redeem(query.get("ticket", [""])[0])
        if token is None:
            return connection.respond(HTTPStatus.UNAUTHORIZED, "ticket not valid\n")
        response = connection.respond(HTTPStatus.OK, "ok\n")
        response.headers["Set-Cookie"] = self.accounts.cookie(token)
        response.headers["Cache-Control"] = "no-store"
        return response

    def _clear_cookie(self, connection, request):
        self.accounts.close_session(token_from(request.headers.get("Cookie")))
        response = connection.respond(HTTPStatus.OK, "ok\n")
        response.headers["Set-Cookie"] = self.accounts.clear_cookie()
        return response

    # ---- the audit log ------------------------------------------------------

    async def _audit_rows(self, session: Session, data: dict) -> dict:
        if self._account(session) is None:
            return {"type": "error", "action": "AUDIT", "error": "Log in to see the audit log."}
        robot = data.get("robot") if isinstance(data.get("robot"), str) else None
        return {"type": "audit", "robot": robot, "rows": self.audit.commands(robot, AUDIT_ROWS)}

    def _export(self, connection, request):
        client = peer_ip(connection, request)
        if not self.accounts.valid(token_from(request.headers.get("Cookie"))):
            self.audit.record("auth_rejected", client=client, path="/audit.jsonl")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "log in first\n")
        self.audit.record("audit_export", client=client, user=self.accounts.user(token_from(request.headers.get("Cookie"))).name)
        body = "".join(json.dumps(row) + "\n" for row in self.audit.commands())
        response = connection.respond(HTTPStatus.OK, body)
        del response.headers["Content-Type"]
        response.headers["Content-Type"] = "application/x-ndjson"
        response.headers["Content-Disposition"] = 'attachment; filename="styri-audit.jsonl"'
        response.headers["Cache-Control"] = "no-store"
        return response

    # ---- users and switches: admins only ---------------------------------------

    async def _admin_only(self, session: Session, action: str, data: dict, handler) -> dict:
        user = self._account(session, touch=True)
        if user is None or not user.can(ADMIN):
            return self._reject(session, action, "Log in as an admin to manage users.")
        try:
            detail = await handler(session, data)
        except AccountError as exc:
            return self._reject(session, action, str(exc).capitalize() + ".")
        if detail is not None:  # passwords never reach the log
            self.audit.record("command", client=session.client, user=user.name, action=action, payload=detail)
        return {"type": "users", "users": self.accounts.list(), "control": self._status(session)}

    async def _users(self, session: Session, data: dict) -> None:
        return None

    async def _user_add(self, session: Session, data: dict) -> dict:
        await asyncio.to_thread(self.accounts.add, data.get("name"), data.get("password"), data.get("role"))
        return {"name": data["name"], "role": data["role"]}

    async def _user_remove(self, session: Session, data: dict) -> dict:
        self.accounts.remove(data.get("name"))
        return {"name": data["name"]}

    async def _user_role(self, session: Session, data: dict) -> dict:
        self.accounts.set_role(data.get("name"), data.get("role"))
        return {"name": data["name"], "role": data["role"]}

    async def _user_password(self, session: Session, data: dict) -> dict:
        await asyncio.to_thread(self.accounts.set_password, data.get("name"), data.get("password"))
        return {"name": data["name"]}

    async def _set_switches(self, session: Session, data: dict) -> dict:
        changed = {}
        for key in ("control", "anonymous_view"):
            if isinstance(data.get(key), bool) and data[key] != getattr(self.switches, key):
                setattr(self.switches, key, data[key])
                changed[key] = data[key]
        self.switches.save()
        if "control" in changed:
            if self.vda is not None:
                self.vda.control = self.switches.control
            if not self.switches.control:
                self.teleop.stop_all("control_off")
            self.bridge.activity.add("warning", f"Robot control turned {'on' if self.switches.control else 'off'}", "control")
        for other in list(self.bridge.sessions):
            if self.bridge.view_gate(other):
                await self.bridge.open_view(other)
            elif other.viewing:
                await self.bridge.close_view(other)
        if changed:
            self.bridge.publish_threadsafe({"type": "switches", "enabled": self.switches.control,
                                            "anonymous_view": self.switches.anonymous_view})
        return changed

    # ---- the node graph ---------------------------------------------------------

    async def _graph_save(self, session: Session, data: dict) -> dict:
        """The map editor's save. An order already running keeps its route."""
        user = self._account(session, touch=True)
        if user is None or not user.can(ADMIN):
            return self._reject(session, "GRAPH_SAVE", "Log in as an admin to edit the map.")
        site = self.bridge.site
        try:
            graph = Graph.from_dict(data.get("graph"))
            if len(graph.nodes) > commands.MAX_NODES:
                raise GraphError(f"at most {commands.MAX_NODES} nodes")
        except GraphError as exc:
            return self._reject(session, "GRAPH_SAVE", f"Graph not saved: {exc}.")
        async with self._saving:  # two saves can't both pass the check
            if data.get("version") != site.version:
                return self._reject(session, "GRAPH_SAVE", GRAPH_CHANGED)
            try:
                await asyncio.to_thread(site.save, graph)
            except OSError as exc:
                return self._reject(session, "GRAPH_SAVE", f"Can't write {site.graph_path}: {exc.strerror or exc}. "
                                                           "Its folder must be writable by Styri (uid 10001), not mounted :ro.")
        if self.vda is not None:
            self.vda.graph = graph
        self.audit.record("command", client=session.client, user=user.name, action="GRAPH_SAVE",
                          payload={"nodes": len(graph.nodes), "edges": len(graph.edges)},
                          user_agent=self._agent(session))
        self.bridge.activity.add("state", f"Node graph saved: {len(graph.nodes)} nodes, {len(graph.edges)} edges", "control")
        self.bridge.publish_threadsafe({"type": "site", "site": site.describe()})
        return {"type": "ack", "action": "GRAPH_SAVE"}

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
        if action == "GOAL" and view.live.paused:
            raise Refused(PAUSED)

    async def _robot_command(self, session: Session, action: str, data: dict) -> dict | None:
        payload = {k: v for k, v in data.items() if k not in ("action", "robot", "id")}
        robot = data.get("robot") if isinstance(data.get("robot"), str) else None
        user = self._account(session, touch=True)
        refused = self._refusal(user, action)
        if refused:
            return self._reject(session, action, refused, robot, payload)
        try:
            view = self._view(data)
            robot = view.id
            self._allow(view, action)
            if action == "OPERATOR_STOP" and user is None and self._too_soon(view):
                return self._reject(session, action, "Stop already sent.", robot, payload, limited=True)
            if action == "TELEOP":
                return self._drive(session, view, data, payload)
            if action == "TELEOP_RELEASE":
                self.teleop.release(view.index, "released", session)
                return None
            before = view.live.task_id
            view.live.goal_rejected = False
            sent = await self._send(view, action, data)
        except CommandError as exc:
            return self._reject(session, action, str(exc), robot, payload)
        except Refused as exc:
            return self._reject(session, action, str(exc), robot, payload)
        except RuntimeError as exc:  # SinkError, VdaError: couldn't be carried out
            return self._reject(session, action, str(exc), robot, payload)
        row = self.audit.record("command", client=session.client, user=self._user(session), action=action, robot=robot,
                                payload={**payload, **sent}, user_agent=self._agent(session))
        if action in TRACKED:
            self._track(view, action, row, self._user(session), data, sent, before)
        if action == "PAUSE":
            view.live.paused_by = self._user(session)
        elif action == "RESUME":
            view.live.paused_by = None
        if action == "OPERATOR_STOP":
            view.monitor.activity.add("warning", f"Operator stop from {session.client} ({self._user(session)})", "control")
        return {"type": "ack", "action": action, "robot": robot, "id": data.get("id")}

    @staticmethod
    def _track(view: RobotView, action: str, row: int, user: str, data: dict, sent: dict, before: str | None) -> None:
        point = (data["x"], data["y"]) if isinstance(data.get("x"), (int, float)) and isinstance(data.get("y"), (int, float)) else None
        view.live.command = Command(row, action, user, time.time(), time.monotonic(), node=(sent.get("nodes") or [None])[-1],
                                    point=point, order=sent.get("order_id"), before=before)

    def _follow_commands(self) -> None:
        """Each command's next step, from what its robot reports. In the model for the panel, in the log to keep."""
        for view in self.bridge.robots:
            step = next_step(view)
            if step is not None:
                cmd = view.live.command
                advance(cmd, *step)
                self.audit.record("command_step", ref=cmd.row, status=cmd.status, steps=cmd.steps, reason=cmd.reason)

    def _refusal(self, user: User | None, action: str) -> str | None:
        """Who may do what. Anyone may stop: it's the safe direction, and undoing one needs an operator."""
        if not self.switches.control:
            return "Robot control is off."
        if action in ("OPERATOR_STOP", "OPERATOR_STOP_ALL"):
            if user is None and (self.stop_requires_login or not self.switches.anonymous_view):
                return "Log in to control robots."
            return None
        if user is None:
            return "Log in to control robots."
        return None if user.can(OPERATOR) else "Log in as an operator to send commands."

    def _too_soon(self, view: RobotView) -> bool:
        """A stop without a login goes through once per robot per ANONYMOUS_STOP_EVERY."""
        now = self.clock()
        if now - self._anonymous_stops.get(view.index, -ANONYMOUS_STOP_EVERY) < ANONYMOUS_STOP_EVERY:
            return True
        self._anonymous_stops[view.index] = now
        return False

    async def _send(self, view: RobotView, action: str, data: dict) -> dict:
        sink = self._sink(view)
        if action == "GOAL":
            sent = await self._goal(view, sink, commands.goal(data))
            stop_over(view.live)
            return sent
        if action == "PAUSE":
            await sink.pause(view)
        elif action == "RESUME":
            await sink.resume(view)
            stop_over(view.live)
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
        stop_sent(view.live)
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
            stop_over(view.live)
            view.live.driver = self._user(session)
            self._drives[view.index] = self.clock()
            self.audit.record("command", client=session.client, user=self._user(session), action="TELEOP", robot=view.id,
                              payload={"event": "start", "limits": [link.max_linear, link.max_angular]})
        return None  # streams at 10-20 Hz: no reply per message

    def _drive_ended(self, session: Session, view: RobotView, reason: str) -> None:
        view.live.driver = None
        seconds = round(self.clock() - self._drives.pop(view.index, self.clock()))
        self.audit.record("command", client=session.client, user=self._user(session), action="TELEOP", robot=view.id,
                          payload={"event": "stop", "reason": reason, "seconds": seconds})

    async def _stop_all(self, session: Session, data: dict) -> dict:
        refused = self._refusal(self._account(session, touch=True), "OPERATOR_STOP_ALL")
        if refused:
            return self._reject(session, "OPERATOR_STOP_ALL", refused)
        robots = [v for v in self.bridge.robots if capabilities(v.map, v.live)["can_stop"]]
        self.bridge.stop_all_run = {"id": self.audit.record("stop_all", client=session.client, user=self._user(session)),
                                    "robots": {v.name: "sent" for v in robots}}
        results = await asyncio.gather(*(self._robot_command(session, "OPERATOR_STOP", {"robot": v.id}) for v in robots))
        # A robot whose stop went out moments ago is stopping: that's not a failure.
        failed = [r["robot"] for r in results if r and r["type"] == "error" and not r.get("limited")]
        self.audit.record("command", client=session.client, user=self._user(session), action="OPERATOR_STOP_ALL",
                          failed=failed, user_agent=self._agent(session))
        return {"type": "ack", "action": "OPERATOR_STOP_ALL", "failed": failed, "id": data.get("id")}
