"""Control end to end over a real WebSocket, with a recording sink."""

import asyncio
import json
import time
import urllib.error
import urllib.request

import pytest
from websockets.asyncio.client import connect

from helpers import run_bridge
from styri_bridge import mapping
from styri_bridge.config import Config
from styri_bridge.control.auth import Admin
from styri_bridge.control.service import Control
from styri_bridge.control.teleop import GAP, Teleop

PASSWORD = "correct horse"


class Sink:
    def __init__(self):
        self.calls = []
        self.vel = []

    def velocity(self, linear, angular):
        self.vel.append((time.monotonic(), linear, angular))

    async def goal(self, view, x, y, theta):
        self.calls.append(("goal", x, y, theta))

    async def pause(self, view):
        self.calls.append(("pause",))

    async def resume(self, view):
        self.calls.append(("resume",))

    async def cancel(self, view):
        self.calls.append(("cancel",))

    async def operator_stop(self, view):
        self.calls.append(("stop",))
        self.velocity(0.0, 0.0)


FILE = {"control": {"enabled": True}, "robots": [
    {"name": "a", "namespace": "/a", "cmd_vel": "/a/cmd_vel", "nav2_action": "/a/nav", "pause_topic": "/a/pause",
     "max_linear": 0.5, "max_angular": 1.0, "points": [{"name": "dock", "x": 1, "y": 2}]},
    {"name": "b", "namespace": "/b"},  # view only: nothing whitelisted
]}


def config():
    robots, _ = mapping.from_dict(FILE, {})
    return Config(audit_db=":memory:", ui_dir=None, mapping=mapping.Loaded(tuple(robots), "test"))


def bridge(test):
    sink, holder = Sink(), {}

    def setup(server):
        admin = Admin(None, env={"STYRI_ADMIN_PASSWORD": PASSWORD})
        holder["control"] = Control(server, admin=admin, sinks={0: sink, 1: Sink()}).attach()

    async def wrapped(url, server, audit):
        for view in server.robots:  # fresh data, so the robots aren't stale
            topic = view.map.value("battery").topic
            view.monitor.discovered([(topic, "sensor_msgs/msg/BatteryState")], lambda _t: True)
            message = {"percentage": 0.8, "voltage": 24.0}
            view.monitor.message(topic, message)
            view.monitor.mapped(topic, message)
            server.snapshot(view.index)
        await test(url, server, audit, sink, holder["control"])
    return run_bridge(wrapped, setup=setup, cfg=config())


async def ask(ws, **msg):
    await ws.send(json.dumps(msg))
    while True:
        reply = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if reply["type"] not in ("event", "snapshot", "fleet", "hello", "activity"):
            return reply


async def login(ws):
    reply = await ask(ws, action="LOGIN", password=PASSWORD)
    assert reply["control"]["logged_in"], reply
    return reply


def rows(audit, kind=None):
    return [r for r in audit.commands() if kind is None or r["kind"] == kind]


def test_commands_need_a_login_and_viewing_does_not():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            hello = json.loads(await ws.recv())
            assert hello["control"] == {"enabled": True, "logged_in": False, "needs_setup": False, "session_hours": 8.0}
            for msg in ({"action": "TELEOP", "robot": "a", "linear": 0.1, "angular": 0},
                        {"action": "GOAL", "robot": "a", "x": 1, "y": 1}, {"action": "PAUSE", "robot": "a"},
                        {"action": "OPERATOR_STOP", "robot": "a"}, {"action": "OPERATOR_STOP_ALL"}):
                reply = await ask(ws, **msg)
                assert reply["type"] == "error" and "Log in" in reply["error"]
            assert (await ask(ws, action="PING", t=1))["type"] == "pong"
            assert (await ask(ws, action="AUDIT"))["type"] == "error"
        assert sink.calls == [] and sink.vel == []
        assert len(rows(audit, "command_rejected")) == 5
    bridge(go)


def test_a_wrong_password_is_refused_and_locks_out():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            for _ in range(5):
                assert "Wrong" in (await ask(ws, action="LOGIN", password="nope"))["error"]
            assert "Too many" in (await ask(ws, action="LOGIN", password=PASSWORD))["error"]
    bridge(go)


def test_first_run_setup_works_once():
    async def go(url, server, audit, sink, control):
        control.admin = Admin(None, env={})
        async with connect(url) as ws:
            assert "at least" in (await ask(ws, action="SETUP", password="short"))["error"]
            reply = await ask(ws, action="SETUP", password=PASSWORD)
            assert reply["control"]["logged_in"] and not reply["control"]["needs_setup"]
            assert "already" in (await ask(ws, action="SETUP", password="another password"))["error"].lower()
    bridge(go)


def get(url, **headers):
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=2)


def test_the_ticket_sets_an_http_only_cookie_once():
    async def go(url, server, audit, sink, control):
        base = url.replace("ws://", "http://").removesuffix("/ws")
        async with connect(url) as ws:
            ticket = (await login(ws))["ticket"]
        res = await asyncio.to_thread(get, f"{base}/api/session?ticket={ticket}")
        cookie = res.headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
        with pytest.raises(urllib.error.HTTPError):
            await asyncio.to_thread(get, f"{base}/api/session?ticket={ticket}")
        value = cookie.split(";")[0]
        async with connect(url, additional_headers={"Cookie": value}) as ws:
            assert json.loads(await ws.recv())["control"]["logged_in"]
            assert (await ask(ws, action="PAUSE", robot="a"))["type"] == "ack"
        body = (await asyncio.to_thread(get, f"{base}/audit.jsonl", Cookie=value)).read().decode()
        assert json.loads(body.splitlines()[-1])["command"] == "PAUSE"
        with pytest.raises(urllib.error.HTTPError):
            await asyncio.to_thread(get, f"{base}/audit.jsonl")
    bridge(go)


def test_sessions_end_after_inactivity():
    now = [0.0]
    admin = Admin(None, session_hours=1, env={"STYRI_ADMIN_PASSWORD": PASSWORD}, clock=lambda: now[0])
    token, _ = admin.open_session()
    now[0] = 3000
    assert admin.valid(token)
    now[0] = 6000  # used at 3000, so still inside the hour
    assert admin.valid(token)
    now[0] = 9601
    assert not admin.valid(token)


def test_speed_caps_are_enforced_in_the_bridge():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            await ws.send(json.dumps({"action": "TELEOP", "robot": "a", "linear": 9, "angular": -9}))
            await ask(ws, action="PING", t=1)
            assert sink.vel[-1][1:] == (0.5, -1.0)
            await ws.send(json.dumps({"action": "TELEOP_RELEASE", "robot": "a"}))
            await ask(ws, action="PING", t=2)
            assert sink.vel[-1][1:] == (0.0, 0.0)  # deadman: zero at once
    bridge(go)


def test_one_driver_at_a_time():
    async def go(url, server, audit, sink, control):
        async with connect(url) as one, connect(url) as two:
            await login(one)
            await login(two)
            await one.send(json.dumps({"action": "TELEOP", "robot": "a", "linear": 0.1, "angular": 0}))
            await ask(one, action="PING", t=1)
            reply = await ask(two, action="TELEOP", robot="a", linear=0.2, angular=0)
            assert reply["error"] == "Being driven by another session"
            assert all(v[1] != 0.2 for v in sink.vel)
    bridge(go)


@pytest.mark.parametrize("run", range(20))
def test_watchdog_stops_within_the_limit_when_the_socket_dies(run):
    async def go(url, server, audit, sink, control):
        ws = await connect(url)
        await login(ws)
        for _ in range(3):
            await ws.send(json.dumps({"action": "TELEOP", "robot": "a", "linear": 0.3, "angular": 0}))
            await asyncio.sleep(0.05)
        ws.transport.abort()
        killed = time.monotonic()
        while not (sink.vel and sink.vel[-1][1] == 0.0) and time.monotonic() - killed < 2:
            await asyncio.sleep(0.005)
        assert sink.vel[-1][1:] == (0.0, 0.0)
        assert sink.vel[-1][0] - killed <= 0.5
    bridge(go)


def test_silence_trips_the_watchdog_with_the_socket_open():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            await ws.send(json.dumps({"action": "TELEOP", "robot": "a", "linear": 0.3, "angular": 0}))
            await ask(ws, action="PING", t=1)
            sent = time.monotonic()
            await asyncio.sleep(GAP + 0.1)
            assert sink.vel[-1][1:] == (0.0, 0.0) and sink.vel[-1][0] - sent <= 0.5
        assert any(r["payload"].get("reason") == "watchdog" for r in rows(audit, "command"))
    bridge(go)


def test_whitelist_rejects_and_logs():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            for msg in ({"action": "TELEOP", "robot": "b", "linear": 0.1, "angular": 0},
                        {"action": "GOAL", "robot": "b", "x": 0, "y": 0},
                        {"action": "PAUSE", "robot": "b"},
                        {"action": "OPERATOR_STOP", "robot": "b"},
                        {"action": "GOAL", "robot": "nobody", "x": 0, "y": 0},
                        {"action": "GOAL", "robot": "a", "point": "not-saved"}):
                assert (await ask(ws, **msg))["type"] == "error", msg
            assert (await ask(ws, action="PUBLISH", topic="/cmd_vel"))["type"] == "error"
        assert len(rows(audit, "command_rejected")) == 7
        assert sink.calls == [] and sink.vel == []
    bridge(go)


def test_stale_robots_keep_only_the_stop():
    async def go(url, server, audit, sink, control):
        server.robots[0].live.online = False
        async with connect(url) as ws:
            await login(ws)
            assert "stale" in (await ask(ws, action="TELEOP", robot="a", linear=0.1, angular=0))["error"]
            assert "stale" in (await ask(ws, action="GOAL", robot="a", x=1, y=1))["error"]
            assert (await ask(ws, action="OPERATOR_STOP", robot="a"))["type"] == "ack"
        assert sink.calls == [("stop",)]
    bridge(go)


def test_commands_reach_the_sink_and_the_audit_log():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            for msg in ({"action": "GOAL", "robot": "a", "x": 3, "y": 4, "theta": 1},
                        {"action": "GOAL", "robot": "a", "point": "dock"},
                        {"action": "PAUSE", "robot": "a"}, {"action": "RESUME", "robot": "a"},
                        {"action": "CANCEL", "robot": "a"}, {"action": "OPERATOR_STOP", "robot": "a"}):
                assert (await ask(ws, **msg))["type"] == "ack", msg
            audit_rows = (await ask(ws, action="AUDIT", robot="a"))["rows"]
        assert sink.calls == [("goal", 3, 4, 1), ("goal", 1, 2, 0), ("pause",), ("resume",), ("cancel",), ("stop",)]
        assert [r["command"] for r in audit_rows] == ["GOAL", "GOAL", "PAUSE", "RESUME", "CANCEL", "OPERATOR_STOP"]
        first = audit_rows[0]
        assert first["user"] == "admin" and first["robot"] == "a" and first["time"] and first["payload"]["x"] == 3
        assert "password" not in json.dumps(audit.rows()).lower().replace("admin_password_set", "")
    bridge(go)


def test_stop_all_reaches_every_robot_that_can_stop():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            reply = await ask(ws, action="OPERATOR_STOP_ALL")
            assert reply["type"] == "ack" and reply["failed"] == []
        assert sink.calls == [("stop",)]
    bridge(go)


def test_operator_stop_ends_the_drive():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            await ws.send(json.dumps({"action": "TELEOP", "robot": "a", "linear": 0.3, "angular": 0}))
            await ask(ws, action="OPERATOR_STOP", robot="a")
            assert control.teleop.driver(0) is None
            assert "in progress" in (await ask(ws, action="TELEOP", robot="a", linear=0.3, angular=0))["error"]
    bridge(go)


def test_with_control_off_there_are_no_commands():
    async def go(url, server, audit):
        async with connect(url) as ws:
            reply = await ask(ws, action="OPERATOR_STOP", robot="a")
            assert "view-only" in reply["error"]
        assert not server.actions
    run_bridge(go)


def test_the_log_is_append_only():
    from styri_bridge.audit import AuditLog
    audit = AuditLog(":memory:")
    audit.record("command", action="PAUSE")
    with pytest.raises(Exception, match="append-only"):
        audit._db.execute("DELETE FROM events")
    with pytest.raises(Exception, match="append-only"):
        audit._db.execute("UPDATE events SET kind = 'x'")


def test_teleop_guard_on_a_fake_clock():
    now = [0.0]
    sent = []
    t = Teleop(clock=lambda: now[0])
    t.drive(0, "s", 0.3, 0.0, lambda a, b: sent.append((a, b)), lambda r: sent.append(r))
    now[0] = GAP - 0.01
    t.check()
    assert sent == [(0.3, 0.0)]
    now[0] = GAP + 0.01
    t.check()
    assert sent == [(0.3, 0.0), (0.0, 0.0), "watchdog"]
