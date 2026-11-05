"""Control end to end over a real WebSocket, with a recording sink."""

import asyncio
import json
import time
import urllib.error
import urllib.request

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from helpers import run_bridge
from styri_bridge import mapping
from styri_bridge.config import Config
from styri_bridge.control.auth import Accounts, Switches
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
     "odom": "/a/odom",
     "max_linear": 0.5, "max_angular": 1.0, "points": [{"name": "dock", "x": 1, "y": 2}]},
    {"name": "b", "namespace": "/b"},  # view only: nothing whitelisted
]}


def config():
    robots, _ = mapping.from_dict(FILE, {})
    return Config(audit_db=":memory:", ui_dir=None, mapping=mapping.Loaded(tuple(robots), "test"))


def bridge(test):
    sink, holder = Sink(), {}

    def setup(server):
        accounts = Accounts(None, env={"STYRI_ADMIN_PASSWORD": PASSWORD})
        holder["control"] = Control(server, accounts=accounts, sinks={0: sink, 1: Sink()}).attach()

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
        if reply["type"] not in ("event", "snapshot", "fleet", "hello", "activity", "site", "switches"):
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
            assert hello["control"] == {"enabled": True, "available": True, "logged_in": False, "user": None,
                                        "needs_setup": False, "session_hours": 8.0, "stop_requires_login": False,
                                        "anonymous_view": True}
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
                assert "Wrong" in (await ask(ws, action="LOGIN", password="nopeeeee"))["error"]
            assert "Too many" in (await ask(ws, action="LOGIN", password=PASSWORD))["error"]
    bridge(go)


def test_first_run_setup_works_once():
    async def go(url, server, audit, sink, control):
        control.accounts = Accounts(None, env={})
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
    accounts = Accounts(None, session_hours=1, env={"STYRI_ADMIN_PASSWORD": PASSWORD}, clock=lambda: now[0])
    token, _ = accounts.open_session()
    now[0] = 3000
    assert accounts.valid(token)
    now[0] = 6000  # used at 3000, so still inside the hour
    assert accounts.valid(token)
    now[0] = 9601
    assert not accounts.valid(token)


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
        holder["c"] = Control(server, accounts=Accounts(None, env={"STYRI_ADMIN_PASSWORD": PASSWORD}), sinks={0: Sink()}).attach()

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


# ---- roles: who may do what, in the bridge -----------------------------------

def team(test, stop_requires_login=False):
    sink, holder = Sink(), {}

    def setup(server):
        accounts = Accounts(None, env={"STYRI_ADMIN_PASSWORD": PASSWORD})
        accounts.add("olive", PASSWORD, "operator")
        accounts.add("vic", PASSWORD, "viewer")
        holder["c"] = Control(server, accounts=accounts, sinks={0: sink, 1: Sink()}).attach()
        holder["c"].stop_requires_login = stop_requires_login

    async def wrapped(url, server, audit):
        for view in server.robots:
            topic = view.map.value("battery").topic
            view.monitor.discovered([(topic, "sensor_msgs/msg/BatteryState")], lambda _t: True)
            view.monitor.message(topic, {"percentage": 0.8, "voltage": 24.0})
            view.monitor.mapped(topic, {"percentage": 0.8, "voltage": 24.0})
            server.snapshot(view.index)
        await test(url, server, audit, sink, holder["c"])
    return run_bridge(wrapped, setup=setup, cfg=config())


async def as_user(ws, name):
    reply = await ask(ws, action="LOGIN", username=name, password=PASSWORD)
    assert reply["control"]["user"]["name"] == name, reply
    return reply


COMMANDS = [{"action": "GOAL", "robot": "a", "x": 1, "y": 1}, {"action": "PAUSE", "robot": "a"},
            {"action": "RESUME", "robot": "a"}, {"action": "CANCEL", "robot": "a"}]
ADMIN_ONLY = [{"action": "USERS"}, {"action": "USER_ADD", "name": "x", "password": PASSWORD, "role": "viewer"},
              {"action": "USER_REMOVE", "name": "vic"}, {"action": "USER_ROLE", "name": "vic", "role": "admin"},
              {"action": "USER_PASSWORD", "name": "vic", "password": PASSWORD}, {"action": "SWITCHES", "control": False},
              {"action": "GRAPH_SAVE", "graph": GRAPH, "version": None}]


@pytest.mark.parametrize("who, commands_work, admin_works", [(None, False, False), ("vic", False, False),
                                                             ("olive", True, False), ("admin", True, True)])
def test_permission_matrix(who, commands_work, admin_works):
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            if who:
                await as_user(ws, who)
            for msg in COMMANDS:
                reply = await ask(ws, **msg)
                assert (reply["type"] == "ack") == commands_work, (who, msg, reply)
            if not admin_works:
                for msg in ADMIN_ONLY:
                    assert (await ask(ws, **msg))["type"] == "error", (who, msg)
                assert len(control.accounts.list()) == 3 and control.switches.control
            await asyncio.sleep(2.1)
            assert (await ask(ws, action="OPERATOR_STOP", robot="a"))["type"] == "ack", who  # everyone can stop
            if who:
                assert (await ask(ws, action="AUDIT"))["type"] == "audit"
    team(go)


def test_a_viewer_is_told_to_log_in_as_an_operator_and_the_log_has_their_name():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await as_user(ws, "vic")
            reply = await ask(ws, action="PAUSE", robot="a")
            assert reply["error"] == "Log in as an operator to send commands."
            await ask(ws, action="OPERATOR_STOP", robot="a")
        assert [r["user"] for r in audit.commands()] == ["vic", "vic"]
    team(go)


def test_with_stop_locked_down_a_viewer_can_still_stop_and_anonymous_cannot():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            assert "Log in" in (await ask(ws, action="OPERATOR_STOP", robot="a"))["error"]
            await as_user(ws, "vic")
            assert (await ask(ws, action="OPERATOR_STOP", robot="a"))["type"] == "ack"
    team(go, stop_requires_login=True)


def test_an_admin_manages_users_and_passwords_stay_out_of_the_log():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await as_user(ws, "admin")
            reply = await ask(ws, action="USER_ADD", name="new.one", password="another password", role="viewer")
            assert "new.one" in [u["name"] for u in reply["users"]]
            await ask(ws, action="USER_ROLE", name="new.one", role="operator")
            await ask(ws, action="USER_PASSWORD", name="new.one", password="a third password")
            await ask(ws, action="USER_REMOVE", name="new.one")
            for bad in ({"action": "USER_ADD", "name": "Bad Name", "password": PASSWORD, "role": "viewer"},
                        {"action": "USER_ADD", "name": "ok", "password": "short", "role": "viewer"},
                        {"action": "USER_ADD", "name": "vic", "password": PASSWORD, "role": "viewer"},
                        {"action": "USER_ADD", "name": "ok", "password": PASSWORD, "role": "king"},
                        {"action": "USER_REMOVE", "name": "nobody"}):
                assert (await ask(ws, **bad))["type"] == "error", bad
        text = json.dumps(audit.rows())
        assert "another password" not in text and "third password" not in text
        assert [r["command"] for r in audit.commands() if r["kind"] == "command"] == \
            ["USER_ADD", "USER_ROLE", "USER_PASSWORD", "USER_REMOVE"]
    team(go)


def test_the_last_admin_stays():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await as_user(ws, "admin")
            assert "last admin" in (await ask(ws, action="USER_REMOVE", name="admin"))["error"]
            assert "last admin" in (await ask(ws, action="USER_ROLE", name="admin", role="viewer"))["error"]
            await ask(ws, action="USER_ROLE", name="olive", role="admin")
            assert (await ask(ws, action="USER_ROLE", name="admin", role="viewer"))["type"] == "users"
    team(go)


def test_a_removed_user_loses_their_session_at_once():
    async def go(url, server, audit, sink, control):
        async with connect(url) as admin, connect(url) as ws:
            await as_user(admin, "admin")
            await as_user(ws, "olive")
            assert (await ask(ws, action="PAUSE", robot="a"))["type"] == "ack"
            await ask(admin, action="USER_REMOVE", name="olive")
            assert (await ask(ws, action="PAUSE", robot="a"))["type"] == "error"
    team(go)


def test_a_role_change_applies_at_once():
    async def go(url, server, audit, sink, control):
        async with connect(url) as admin, connect(url) as ws:
            await as_user(admin, "admin")
            await as_user(ws, "olive")
            await ask(admin, action="USER_ROLE", name="olive", role="viewer")
            assert "operator" in (await ask(ws, action="PAUSE", robot="a"))["error"]
    team(go)


def test_control_off_stops_a_drive_refuses_everything_and_on_brings_it_back():
    async def go(url, server, audit, sink, control):
        async with connect(url) as admin:
            await as_user(admin, "admin")
            await admin.send(json.dumps({"action": "TELEOP", "robot": "a", "linear": 0.3, "angular": 0}))
            await ask(admin, action="SWITCHES", control=False)
            assert sink.vel[-1][1:] == (0.0, 0.0)
            for msg in ({"action": "PAUSE", "robot": "a"}, {"action": "OPERATOR_STOP", "robot": "a"}, {"action": "OPERATOR_STOP_ALL"}):
                assert (await ask(admin, **msg))["error"] == "Robot control is off."
            await ask(admin, action="SWITCHES", control=True)
            assert (await ask(admin, action="PAUSE", robot="a"))["type"] == "ack"
    team(go)


def test_anonymous_viewing_off_sends_a_stranger_nothing():
    async def go(url, server, audit, sink, control):
        async with connect(url) as admin, connect(url) as stranger:
            await as_user(admin, "admin")
            await ask(admin, action="SWITCHES", anonymous_view=False)

            async def nothing_about_robots(ws, seconds=2.5):
                got = []
                try:
                    async with asyncio.timeout(seconds):
                        while True:
                            got.append(json.loads(await ws.recv()))
                except TimeoutError:
                    pass
                return got

            first = await nothing_about_robots(stranger)
            assert any(m["type"] == "hello" and m.get("locked") and m["robots"] == [] for m in first)
            after = first[[i for i, m in enumerate(first) if m.get("locked")][-1] + 1:]
            assert not [m for m in after if m["type"] in ("snapshot", "fleet", "event", "activity")]

            async with connect(url) as late:
                seen = await nothing_about_robots(late, 1.5)
                assert [m["type"] for m in seen if m["type"] != "switches"] == ["hello"]
                assert (await ask(late, action="SELECT", topic="/x"))["type"] == "error"
                assert "Log in" in (await ask(late, action="OPERATOR_STOP", robot="a"))["error"]
                await as_user(late, "vic")
                kinds = {m["type"] for m in await nothing_about_robots(late, 1.5)}
                assert "fleet" in kinds
                await ask(late, action="LOGOUT")
                await asyncio.sleep(0.1)
                while True:  # drain what was in flight, then silence
                    try:
                        async with asyncio.timeout(0.05):
                            await late.recv()
                    except TimeoutError:
                        break
                assert not [m for m in await nothing_about_robots(late, 1.5) if m["type"] in ("snapshot", "fleet")]
    team(go)


def test_switches_survive_a_restart(tmp_path):
    path = str(tmp_path / "switches.json")
    s = Switches(path)
    s.control, s.anonymous_view = False, False
    s.save()
    again = Switches(path)
    assert not again.control and not again.anonymous_view


def test_an_old_admin_password_becomes_the_admin_account(tmp_path):
    from styri_bridge.control.auth import hash_password
    (tmp_path / "admin.hash").write_text(hash_password(PASSWORD))
    accounts = Accounts(str(tmp_path / "users.json"), env={})
    assert accounts.check("c", "admin", PASSWORD).role == "admin"
    assert not (tmp_path / "admin.hash").exists()


def test_the_terminal_tool_and_a_running_panel_share_accounts(tmp_path, capsys, monkeypatch):
    import io
    from styri_bridge.control import users_cli
    path = str(tmp_path / "users.json")
    panel = Accounts(path, env={"STYRI_ADMIN_PASSWORD": PASSWORD})
    run = lambda *a: users_cli.main(["--file", path, *a])  # noqa: E731
    monkeypatch.setattr("sys.stdin", io.StringIO("a good password\n"))
    assert run("add", "m.lind", "--role", "operator", "--password-stdin") == 0
    assert panel.get("m.lind").role == "operator"
    assert run("role", "m.lind", "viewer") == 0 and panel.get("m.lind").role == "viewer"
    assert run("list") == 0 and "m.lind" in capsys.readouterr().out
    assert run("remove", "admin") == 1 and "last admin" in capsys.readouterr().err
    assert run("remove", "m.lind") == 0 and panel.get("m.lind") is None


# ---- what the panel shows about commands, and sessions ------------------------

def fleet_of(server, name="a"):
    return next(r for r in server.fleet()["robots"] if r["name"] == name)


def test_a_command_steps_along_in_the_model_and_in_the_log():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            await ask(ws, action="GOAL", robot="a", x=1.0, y=2.0, theta=0.0)
            server.snapshot(0)
            assert fleet_of(server)["command"]["status"] == "sent"
            live = server.robots[0].live
            live.task_id, live.task_state = "g1", "active"
            cmd = fleet_of(server)["command"]
            assert (cmd["status"], cmd["point"], cmd["user"]) == ("running", (1.0, 2.0), "admin")
            live.task_state = "done"
            assert fleet_of(server)["command"]["status"] == "done"
            (row,) = rows(audit, "command")
            assert row["status"] == "done" and row["steps"] == ["sent", "accepted", "running", "done"]
    bridge(go)


def test_a_goal_a_stop_took_over_is_interrupted_not_running_for_ever():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            await ask(ws, action="GOAL", robot="a", x=1.0, y=2.0, theta=0.0)
            server.snapshot(0)
            live = server.robots[0].live
            live.task_id, live.task_state = "g1", "active"
            assert fleet_of(server)["command"]["status"] == "running"
            await ask(ws, action="OPERATOR_STOP", robot="a")
            goal = next(r for r in (await ask(ws, action="AUDIT", robot="a"))["rows"] if r["command"] == "GOAL")
            assert goal["status"] == "interrupted"
    bridge(go)


def test_a_browser_that_just_left_does_not_stop_a_switch():
    async def go(url, server, audit, sink, control):
        async with connect(url) as admin, connect(url) as gone, connect(url) as wall:
            await login(admin)
            await ask(admin, action="SWITCHES", anonymous_view=False)
            strangers = [s for s in server.sessions if not s.viewing]
            assert len(strangers) == 2
            first = strangers[0]

            async def closed(_):
                raise ConnectionClosed(None, None)
            first.ws.send = closed
            reply = await ask(admin, action="SWITCHES", anonymous_view=True)
            assert reply["type"] != "error"
            assert strangers[1].viewing
    bridge(go)


def test_a_refusal_is_refused_in_the_log_and_never_a_step():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await ask(ws, action="GOAL", robot="a", x=1.0, y=2.0, theta=0.0)
            (row,) = rows(audit, "command_rejected")
            assert row["status"] == "refused"
    bridge(go)


def test_the_model_says_who_paused_a_robot():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            await ask(ws, action="PAUSE", robot="a")
            server.robots[0].live.paused = True
            server.snapshot(0)
            assert fleet_of(server)["paused_by"] == "admin"
            await ask(ws, action="RESUME", robot="a")
            server.robots[0].live.paused = False
            assert fleet_of(server)["paused_by"] is None
    bridge(go)


def test_the_model_says_who_is_driving():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            await ws.send(json.dumps({"action": "TELEOP", "robot": "a", "linear": 0.1, "angular": 0.0}))
            await asyncio.sleep(0.05)
            server.snapshot(0)
            assert fleet_of(server)["driver"] == "admin"
            await ws.send(json.dumps({"action": "TELEOP_RELEASE", "robot": "a"}))
            await asyncio.sleep(0.05)
            assert fleet_of(server)["driver"] is None
            stop = [r for r in rows(audit, "command") if r["payload"].get("event") == "stop"]
            assert stop[0]["payload"]["seconds"] == 0
    bridge(go)


def test_stop_all_progress_is_in_the_fleet_message():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            await ask(ws, action="OPERATOR_STOP_ALL")
            server.snapshot(0)
            assert server.fleet()["stop_all"]["robots"] == {"a": "sent"}
            live = server.robots[0].live
            live.stop_replied, live.stop_done_at = True, time.monotonic()
            assert server.fleet()["stop_all"]["robots"] == {"a": "stopped"}
            live.stop_sent_at = None  # something else was asked of it
            assert server.fleet()["stop_all"] is None
    bridge(go)


def test_a_session_about_to_end_says_so_and_can_be_kept():
    async def go(url, server, audit, sink, control):
        async with connect(url) as ws:
            await login(ws)
            now = [control.accounts.clock()]
            control.accounts.clock = lambda: now[0]
            now[0] += control.accounts.lifetime - 100
            await control.session_notices()
            while (notice := json.loads(await asyncio.wait_for(ws.recv(), 3)))["type"] != "session":
                pass
            assert 90 <= notice["ends_in"] <= 100
            assert (await ask(ws, action="SESSION_KEEP"))["control"]["logged_in"]
            now[0] += control.accounts.lifetime - 100
            await control.session_notices()
            now[0] += 200
            await control.session_notices()
            while (ended := json.loads(await asyncio.wait_for(ws.recv(), 3)))["type"] != "auth":
                pass
            assert not ended["control"]["logged_in"]
    bridge(go)


def test_the_user_list_says_who_is_online():
    accounts = Accounts(None, env={})
    accounts.add("olive", PASSWORD, "operator")
    assert accounts.list()[0]["active"] is False
    accounts.open_session("olive")
    assert accounts.list()[0]["active"] is True
