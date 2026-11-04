"""The v2.0 acceptance test: one ROS 2 robot and two VDA 5050 vehicles, one panel, no internet.

Run inside the Styri container of examples/mixed-fleet:
  docker compose exec -T styri /ros_entrypoint.sh python3 - < e2e/mixed-fleet/accept.py
"""

import asyncio
import json
import os
import socket
import sys
import time

import aiomqtt
from websockets.asyncio.client import connect

PASSWORD = os.environ.get("STYRI_ADMIN_PASSWORD", "styri-demo")
NO_INTERNET = os.environ.get("EXPECT_NO_INTERNET") == "1"
# Where each robot may be sent. Each goes to the first that's away from where it is, so
# this passes wherever an earlier suite left it.
GOALS = json.loads(os.environ.get("GOALS") or """{"amr-01": [{"x": 6, "y": 4}, {"x": 1, "y": 1}],
    "agv-07": [{"node": "n3"}, {"node": "n1"}], "agv-08": [{"node": "n6"}, {"node": "n1"}]}""")
fleet: dict = {}


async def wait_for_panel():
    """The panel and its broker take a moment after `docker compose up`."""
    deadline = time.monotonic() + 60
    while True:
        try:
            async with aiomqtt.Client("127.0.0.1"):
                pass
            async with connect("ws://127.0.0.1:8080/ws", origin="http://127.0.0.1:8080"):
                return
        except (OSError, aiomqtt.MqttError):
            if time.monotonic() > deadline:
                sys.exit("FAIL the panel or its broker didn't come up in 60 s")
            await asyncio.sleep(0.5)


def step(text):
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


async def listen(ws, replies):
    async for raw in ws:
        msg = json.loads(raw)
        if msg["type"] == "fleet":
            fleet.update({r["name"]: r for r in msg["robots"]})
        elif msg["type"] in ("ack", "error", "auth"):
            replies.put_nowait(msg)


async def until(what, test, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if test():
            step(f"OK   {what}")
            return
        await asyncio.sleep(0.2)
    print(json.dumps(fleet, indent=1, default=str)[:3000])
    sys.exit(f"FAIL {what}")


async def main():
    await wait_for_panel()
    if NO_INTERNET:
        with socket.socket() as s:
            s.settimeout(3)
            try:
                s.connect(("1.1.1.1", 53))
                sys.exit("FAIL this network has a route to the internet")
            except OSError as exc:
                step(f"OK   no route out ({exc})")
    async with connect("ws://127.0.0.1:8080/ws", origin="http://127.0.0.1:8080") as ws:
        replies: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(listen(ws, replies))

        async def ask(**msg):
            await ws.send(json.dumps(msg))
            reply = await asyncio.wait_for(replies.get(), 10)
            if reply["type"] == "error" or reply.get("error"):
                sys.exit(f"FAIL {msg}: {reply}")
            return reply

        names = sorted(GOALS)
        await until("all three robots on the panel, fresh", lambda: all(
            n in fleet and not fleet[n]["stale"] and fleet[n]["pose"] for n in names), 60)
        await until("each VDA factsheet is in its robot detail", lambda: all(
            fleet[n]["factsheet"] and fleet[n]["factsheet"]["typeSpecification"]["seriesName"] == "virtual"
            for n in names if fleet[n]["protocol"] == "vda5050"))
        await ask(action="LOGIN", password=PASSWORD)
        step("OK   logged in")

        start = {n: dict(fleet[n]["pose"]) for n in names}
        def away(name, goal):
            robot = fleet[name]
            if "node" in goal:
                return robot["task"]["last_node"] != goal["node"]
            return abs(robot["pose"]["x"] - goal["x"]) + abs(robot["pose"]["y"] - goal["y"]) > 1

        for name, goals in GOALS.items():
            await ask(action="GOAL", robot=name, **next(g for g in goals if away(name, g)))
        await until("every robot took its goal and is moving", lambda: all(
            fleet[n]["task"]["state"] == "active" and fleet[n]["pose"] != start[n] for n in names))

        # Nav2 has no standard pause: a robot without a pause_topic has no Pause, and that's by design.
        pausable = [n for n in names if fleet[n]["capabilities"]["can_pause"]]
        for name in pausable:
            await ask(action="PAUSE", robot=name)
        await until("every robot that can pause reports paused", lambda: all(fleet[n]["paused"] for n in pausable))
        await asyncio.sleep(1)
        held = {n: dict(fleet[n]["pose"]) for n in pausable}
        await asyncio.sleep(2)
        moved = [n for n in pausable if abs(fleet[n]["pose"]["x"] - held[n]["x"]) + abs(fleet[n]["pose"]["y"] - held[n]["y"]) > 0.02]
        if moved:
            sys.exit(f"FAIL still moving while paused: {moved}")
        step("OK   paused robots stood still")

        for name in pausable:
            await ask(action="RESUME", robot=name)
        await until("every robot moving again", lambda: all(not fleet[n]["paused"] for n in pausable))

        reply = await ask(action="OPERATOR_STOP_ALL")
        if reply["failed"]:
            sys.exit(f"FAIL Operator stop failed for {reply['failed']}")
        await until("no VDA vehicle is driving after Operator stop", lambda: all(
            fleet[n]["driving"] is False for n in names if fleet[n]["protocol"] == "vda5050"), 10)
        await until("every task ended after Operator stop", lambda: all(
            fleet[n]["task"]["state"] in ("idle", "paused") for n in names), 10)
        await asyncio.sleep(1)
        held = {n: dict(fleet[n]["pose"]) for n in names}
        await asyncio.sleep(3)
        moved = [n for n in names if abs(fleet[n]["pose"]["x"] - held[n]["x"]) + abs(fleet[n]["pose"]["y"] - held[n]["y"]) > 0.02]
        if moved:
            sys.exit(f"FAIL still moving after Operator stop: {moved}")
        step("OK   every robot stayed put after Operator stop")
        task.cancel()
    print("PASS mixed-fleet acceptance")


asyncio.run(main())
