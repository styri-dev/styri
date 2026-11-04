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
        if reply["type"] not in ("event", "snapshot", "fleet", "hello", "activity", "site"):
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
            assert hello["control"] == {"enabled": True, "logged_in": False, "needs_setup": False, "session_hours": 8.0,
                                        "stop_requires_login": False}
            for msg in ({"action": "TELEOP", "robot": "a", "linear": 0.1, "angular": 0},
                        {"action": "GOAL", "robot": "a", "x": 1, "y": 1}, {"action": "PAUSE", "robot": "a"},
                        {"action": "RESUME", "robot": "a"}, {"action": "CANCEL", "robot": "a"}):
                reply = await ask(ws, **msg)
                assert reply["type"] == "error" and "Log in" in reply["error"]
            assert (await ask(ws, action="PING", t=1))["type"] == "pong"
            assert (await ask(ws, action="AUDIT"))["type"] == "error"
        assert sink.calls == [] and sink.vel == []
        assert len(rows(audit, "command_rejected")) == 5
    bridge(go)


def test_anyone_can_stop_and_it_is_audited_as_anonymous():
    async def go(url, server, audit, sink, control):
        async with connect(url, user_agent_header="floor-tablet") as ws:
            assert (await ask(ws, action="OPERATOR_STOP", robot="a"))["type"] == "ack"
        assert sink.calls == [("stop",)]
        (row,) = rows(audit, "command")
        assert row["user"] == "anonymous" and row["client"] == "127.0.0.1" and row["user_agent"] == "floor-tablet"
    bridge(go)


def test_anonymous_stop_all_reaches_the_fleet():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            reply = await ask(ws, action="OPERATOR_STOP_ALL")
            assert reply["type"] == "ack" and reply["failed"] == []
        assert sink.calls == [("stop",)]
        assert {r["user"] for r in rows(audit, "command")} == {"anonymous"}
    bridge(go)


def test_undoing_a_stop_needs_the_login():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await ask(ws, action="OPERATOR_STOP", robot="a")
            for msg in ({"action": "RESUME", "robot": "a"}, {"action": "GOAL", "robot": "a", "x": 1, "y": 1},
                        {"action": "TELEOP", "robot": "a", "linear": 0.1, "angular": 0}):
                reply = await ask(ws, **msg)
                assert reply["type"] == "error" and "Log in" in reply["error"], msg
        assert sink.calls == [("stop",)]
        assert not [v for v in sink.vel if v[1] != 0.0]
    bridge(go)


def test_anonymous_stops_are_rate_limited_per_robot_and_every_one_is_logged():
    async def go(url, server, audit, sink, control):
        now = [100.0]
        control.clock = lambda: now[0]
        async with connect(url) as ws:
            assert (await ask(ws, action="OPERATOR_STOP", robot="a"))["type"] == "ack"
            now[0] += 1.9
            reply = await ask(ws, action="OPERATOR_STOP", robot="a")
            assert reply["type"] == "error" and reply["limited"]
            now[0] += 0.2
            assert (await ask(ws, action="OPERATOR_STOP", robot="a"))["type"] == "ack"
        assert sink.calls == [("stop",), ("stop",)]
        assert [r["kind"] for r in rows(audit)] == ["command", "command_rejected", "command"]
    bridge(go)


def test_a_limited_robot_is_not_a_failed_stop_all():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await ask(ws, action="OPERATOR_STOP", robot="a")
            assert (await ask(ws, action="OPERATOR_STOP_ALL"))["failed"] == []
    bridge(go)


def test_a_login_is_never_rate_limited():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            for _ in range(3):
                assert (await ask(ws, action="OPERATOR_STOP", robot="a"))["type"] == "ack"
        assert len(sink.calls) == 3 and {r["user"] for r in rows(audit, "command")} == {"admin"}
    bridge(go)


def test_a_site_can_lock_the_stop_down():
    async def go(url, server, audit, sink, control):
        control.stop_requires_login = True
        async with connect(url) as ws:
            assert json.loads(await ws.recv())["control"]["stop_requires_login"]
            for msg in ({"action": "OPERATOR_STOP", "robot": "a"}, {"action": "OPERATOR_STOP_ALL"}):
                assert "Log in" in (await ask(ws, **msg))["error"]
            assert sink.calls == []
            await login(ws)
            assert (await ask(ws, action="OPERATOR_STOP", robot="a"))["type"] == "ack"
        assert sink.calls == [("stop",)]
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


GRAPH = {"nodes": [{"id": "a", "x": 0, "y": 0, "map_id": "m"}, {"id": "b", "x": 4, "y": 0, "map_id": "m"}],
         "edges": [{"id": "ab", "start": "a", "end": "b"}]}


def save(ws, server, graph):
    return ask(ws, action="GRAPH_SAVE", graph=graph, version=server.site.version)


def editing(tmp_path, test):
    """A bridge whose site.graph is a file in tmp_path that doesn't exist yet."""
    path = tmp_path / "graph.json"
    robots, _ = mapping.from_dict(FILE, {})
    settings = mapping.Settings(control=True, graph=str(path))
    cfg = Config(audit_db=":memory:", ui_dir=None, mapping=mapping.Loaded(tuple(robots), "test", settings=settings))
    holder = {}

    def setup(server):
        holder["c"] = Control(server, admin=Admin(None, env={"STYRI_ADMIN_PASSWORD": PASSWORD}), sinks={0: Sink()}).attach()

    async def wrapped(url, server, audit):
        await test(url, server, audit, holder["c"], path)
    return run_bridge(wrapped, setup=setup, cfg=cfg)


def test_saving_the_graph_writes_the_same_json_and_tells_everyone(tmp_path):
    async def go(url, server, audit, control, path):
        class Vda:
            graph = None
        control.vda = Vda()
        async with connect(url) as ws, connect(url) as watcher:
            hello = json.loads(await watcher.recv())
            assert hello["site"]["editable"] and hello["site"]["graph"] == {"nodes": [], "edges": []}
            await login(ws)
            assert (await save(ws, server, GRAPH))["type"] == "ack"
            while (msg := json.loads(await asyncio.wait_for(watcher.recv(), 3)))["type"] != "site":
                pass
        assert msg["site"]["graph"] == GRAPH
        assert json.loads(path.read_text()) == GRAPH
        assert control.vda.graph.route("a", "b") and server.site.graph.nodes["b"].x == 4
        (row,) = [r for r in audit.commands() if r["command"] == "GRAPH_SAVE"]
        assert row["user"] == "admin" and row["payload"] == {"nodes": 2, "edges": 1}
    editing(tmp_path, go)


def test_saving_the_graph_needs_the_login(tmp_path):
    async def go(url, server, audit, control, path):
        async with connect(url) as ws:
            assert "Log in" in (await save(ws, server, GRAPH))["error"]
        assert not path.exists() and audit.commands()[0]["kind"] == "command_rejected"
    editing(tmp_path, go)


@pytest.mark.parametrize("graph, needle", [
    ({"nodes": [{"id": "a"}], "edges": []}, "need id"),
    ({"nodes": [], "edges": [{"id": "e", "start": "a", "end": "b"}]}, "isn't in the graph"),
    ("nonsense", "need id"),
])
def test_a_bad_graph_changes_nothing(tmp_path, graph, needle):
    async def go(url, server, audit, control, path):
        async with connect(url) as ws:
            await login(ws)
            assert (await save(ws, server, GRAPH))["type"] == "ack"
            reply = await save(ws, server, graph)
            assert reply["type"] == "error" and needle in reply["error"]
        assert json.loads(path.read_text()) == GRAPH and len(server.site.graph.nodes) == 2
    editing(tmp_path, go)


def test_a_read_only_mount_says_what_to_do(tmp_path):
    async def go(url, server, audit, control, path):
        def fail(graph):
            raise OSError(30, "Read-only file system")
        server.site.save = fail
        async with connect(url) as ws:
            await login(ws)
            reply = await save(ws, server, GRAPH)
        assert "Read-only file system" in reply["error"] and ":ro" in reply["error"]
        assert server.site.graph.nodes == {}  # still the graph that's on disk
    editing(tmp_path, go)


def test_a_second_editor_is_told_to_reload(tmp_path):
    async def go(url, server, audit, control, path):
        async with connect(url) as one, connect(url) as two:
            await login(one)
            await login(two)
            opened = server.site.version  # both open the editor now
            assert (await ask(one, action="GRAPH_SAVE", graph=GRAPH, version=opened))["type"] == "ack"
            later = {**GRAPH, "edges": []}
            reply = await ask(two, action="GRAPH_SAVE", graph=later, version=opened)
            assert reply["type"] == "error" and reply["error"] == "The graph changed since you opened it. Reload."
            assert (await ask(two, action="GRAPH_SAVE", graph=later))["type"] == "error"  # no version at all
        assert json.loads(path.read_text()) == GRAPH
        assert audit.commands()[-1]["kind"] == "command_rejected"
    editing(tmp_path, go)


def test_a_paused_robot_takes_no_goal_and_it_is_logged():
    async def go(url, server, audit, sink, control):
        server.robots[0].live.paused = True
        async with connect(url) as ws:
            await login(ws)
            reply = await ask(ws, action="GOAL", robot="a", x=1, y=1)
            assert reply["type"] == "error" and reply["error"] == "This robot is paused. Press Resume first."
            assert (await ask(ws, action="GOAL", robot="a", point="dock"))["type"] == "error"
            assert (await ask(ws, action="RESUME", robot="a"))["type"] == "ack"
        assert sink.calls == [("resume",)]
        rejected = rows(audit, "command_rejected")
        assert len(rejected) == 2 and rejected[0]["reason"] == "This robot is paused. Press Resume first."
    bridge(go)


def test_anonymous_messages_stay_small_and_a_login_gets_room(tmp_path):
    from websockets.exceptions import ConnectionClosed
    padded = json.dumps({"action": "PING", "t": 1, "pad": "x" * (20 * 1024)})

    async def closed_for_size(ws):
        """Snapshots keep coming, so give up after a few seconds rather than hang."""
        with pytest.raises(ConnectionClosed) as closed:
            async with asyncio.timeout(4):
                while True:
                    await ws.recv()
        assert closed.value.rcvd.code == 1009  # too big

    async def until(ws, kind):
        async with asyncio.timeout(4):
            while (msg := json.loads(await ws.recv()))["type"] != kind:
                pass
        return msg

    async def go(url, server, audit, control, path):
        async with connect(url) as ws:
            await ws.send(padded)
            await closed_for_size(ws)
        async with connect(url) as ws:
            await login(ws)
            await ws.send(padded)
            await until(ws, "pong")
            await ws.send(json.dumps({"action": "LOGOUT"}))
            await until(ws, "auth")
            await ws.send(padded)
            await closed_for_size(ws)
    editing(tmp_path, go)


def test_a_big_graph_fits_in_one_message(tmp_path):
    big = {"nodes": [{"id": f"n{i}", "x": i, "y": i, "map_id": "plant-a"} for i in range(1000)], "edges": []}

    async def go(url, server, audit, control, path):
        async with connect(url, max_size=None) as ws:
            await login(ws)
            assert (await save(ws, server, big))["type"] == "ack"
    editing(tmp_path, go)


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
