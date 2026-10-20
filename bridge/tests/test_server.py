"""The Core server end to end: read-only protocol, one port for UI + data."""

import asyncio
import json
import urllib.error
import urllib.request

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from helpers import connect_panel, recv_reply, recv_type, run_bridge, send


def http_get(url, path):
    return urllib.request.urlopen(url.replace("ws://", "http://").removesuffix("/ws") + path)


@pytest.mark.parametrize("msg", [
    {"action": "ESTOP"},
    {"action": "DISPATCH", "target": "DOCK"},
    {"action": "CMD_VEL", "linear": 0.3},
    {"action": "LOGIN", "username": "a", "password": "b"},
    {"action": "PUBLISH", "topic": "/cmd_vel", "data": {}},
])
def test_everything_but_reads_is_refused(msg):
    async def t(url, server, audit):
        ws = await connect_panel(url)
        await send(ws, **msg)
        reply = await recv_reply(ws)
        assert reply["type"] == "error" and "read-only" in reply["error"]
        await ws.close()

    audit = run_bridge(t)
    assert [r[5] for r in audit.rows() if r[2] == "command_rejected"] == [msg["action"]]


def test_garbage_is_an_error_not_a_crash():
    async def t(url, server, audit):
        ws = await connect_panel(url)
        for raw in ("not json", "[1]", '{"action": 5}', '{"action": "PING", "t": "x"}'):
            await ws.send(raw)
            assert (await recv_reply(ws))["type"] == "error"
        await send(ws, action="PING", t=1)
        assert (await recv_reply(ws))["type"] == "pong"  # still connected
        await ws.close()

    run_bridge(t)


def test_hello_activity_history_and_live_events():
    async def t(url, server, audit):
        ws = await connect(url)
        hello = json.loads(await ws.recv())
        assert hello == {"type": "hello", "version": hello["version"], "robot": "test-bot", "domain": hello["domain"],
                         "stale_after": 5.0, "controls": False, "min_voltage": None}
        history = json.loads(await ws.recv())
        assert history["type"] == "activity"
        assert any(e["msg"].startswith("styri v") for e in history["events"])
        event = await recv_type(ws, "event")
        assert event["event"]["kind"] == "connection" and "Browser connected" in event["event"]["msg"]
        await ws.close()

    run_bridge(t)


def test_ping_snapshot_and_topic_inspection():
    def setup(server):
        server.monitor.discovered([("/odom", "nav_msgs/msg/Odometry"), ("/custom", "acme_msgs/msg/Thing")],
                                  lambda type_: type_ != "acme_msgs/msg/Thing")
        server.monitor.message("/odom", {"pose": {"x": 1.5}})

    async def t(url, server, audit):
        ws = await connect_panel(url)
        await send(ws, action="PING", t=123.5)
        assert await recv_reply(ws) == {"type": "pong", "t": 123.5}

        snap = await recv_type(ws, "snapshot")
        names = {row["name"]: row for row in snap["topics"]}
        assert names["/odom"]["age"] is not None and names["/custom"]["supported"] is False
        assert snap["robot_found"] is False and snap["robot"] == "test-bot"

        await send(ws, action="SELECT", topic="/odom")
        reply = await recv_reply(ws)
        assert reply["msg_type"] == "nav_msgs/msg/Odometry" and "x: 1.5" in reply["text"]
        await send(ws, action="SELECT", topic="/custom")
        assert "not installed" in (await recv_reply(ws))["note"]
        await send(ws, action="SELECT", topic="/nope")
        assert (await recv_reply(ws))["error"] == "unknown topic"
        await ws.close()

    run_bridge(t, setup=setup)


def test_telemetry_broadcast_from_another_thread():
    async def t(url, server, audit):
        a, b = await connect_panel(url), await connect_panel(url)
        payload = {"type": "custom", "x": 1}
        await asyncio.to_thread(server.publish_threadsafe, payload)
        assert await recv_reply(a) == payload
        assert await recv_reply(b) == payload
        # NaN would produce invalid JSON; it must be dropped, not sent.
        await asyncio.to_thread(server.publish_threadsafe, {"type": "custom", "x": float("nan")})
        await a.close(); await b.close()

    run_bridge(t)


def test_cross_origin_websocket_refused():
    async def t(url, server, audit):
        with pytest.raises(InvalidStatus):
            await connect(url, origin="http://evil.example")
        host = url.removeprefix("ws://").removesuffix("/ws")
        ws = await connect_panel(url, origin=f"http://{host}")
        await ws.close()

    audit = run_bridge(t)
    assert "origin_rejected" in [r[2] for r in audit.rows()]


def test_serves_the_ui_on_the_same_port(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>styri</title>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")

    async def t(url, server, audit):
        get = lambda path: asyncio.to_thread(http_get, url, path)
        index = await get("/")
        assert index.headers["Content-Type"].startswith("text/html")
        assert "default-src 'self'" in index.headers["Content-Security-Policy"]
        assert b"<title>styri</title>" in index.read()

        asset = await get("/assets/app-abc123.js")
        assert "immutable" in asset.headers["Cache-Control"]
        assert asset.headers["Content-Type"].startswith("text/javascript")

        assert b"<title>" in (await get("/topics")).read()  # client-side route
        for missing in ("/assets/nope.js", "/../secret.txt", "/audit.csv"):
            with pytest.raises(urllib.error.HTTPError) as err:
                await get(missing)
            assert err.value.code == 404
        assert (await get("/healthz")).read() == b"ok\n"

        ws = await connect_panel(url)  # the WebSocket still works alongside
        await ws.close()

    run_bridge(t, ui_dir=str(tmp_path))


def test_extensions_can_add_actions():
    """The hook editions build on. Core registers none."""
    def setup(server):
        async def hello_action(session, data):
            return {"type": "ext", "echo": data.get("x")}
        server.actions["EXT_ECHO"] = hello_action
        server.hello_extra["edition"] = "test"

    async def t(url, server, audit):
        ws = await connect(url)
        assert json.loads(await ws.recv())["edition"] == "test"
        await ws.recv()  # activity
        await send(ws, action="EXT_ECHO", x=7)
        assert await recv_reply(ws) == {"type": "ext", "echo": 7}
        await ws.close()

    run_bridge(t, setup=setup)


def test_core_installs_no_extensions():
    from importlib.metadata import entry_points
    assert list(entry_points(group="styri.extensions")) == []
