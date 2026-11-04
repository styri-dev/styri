"""The watchdog and the deadman, measured on the robot's real /cmd_vel topic.

Run inside the Styri container of examples/mixed-fleet:
  docker compose exec -T styri /ros_entrypoint.sh python3 - < e2e/mixed-fleet/watchdog.py

Each run drives at 15 Hz, then kills the socket, or goes silent, or lets go, and
times the first zero velocity seen on the topic. Limit: 500 ms, every run.
"""

import asyncio
import json
import os
import statistics
import sys
import threading
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from websockets.asyncio.client import connect

URL = "ws://127.0.0.1:8080/ws"
ROBOT, TOPIC = "amr-01", "/amr01/cmd_vel"
RUNS, LIMIT = 20, 0.5
PASSWORD = os.environ.get("STYRI_ADMIN_PASSWORD", "styri-demo")

rclpy.init()
probe = Node("styri_watchdog_probe")
seen: list[tuple[float, float]] = []
probe.create_subscription(Twist, TOPIC, lambda m: seen.append((time.monotonic(), m.linear.x)),
                          QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=100))
threading.Thread(target=rclpy.spin, args=(probe,), daemon=True).start()


async def session():
    ws = await connect(URL, origin="http://127.0.0.1:8080")
    await ws.send(json.dumps({"action": "LOGIN", "password": PASSWORD}))
    while True:
        msg = json.loads(await ws.recv())
        if msg["type"] == "auth":
            if not msg["control"]["logged_in"]:
                sys.exit(f"FAIL login: {msg}")
            return ws


async def drive(ws):
    for _ in range(8):
        await ws.send(json.dumps({"action": "TELEOP", "robot": ROBOT, "linear": 0.2, "angular": 0}))
        await asyncio.sleep(1 / 15)


async def first_zero(since):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        zero = next((t for t, v in seen if t >= since and v == 0.0), None)
        if zero is not None:
            return zero - since
        await asyncio.sleep(0.002)
    sys.exit("FAIL no zero velocity within 2 s")


async def kill(ws):
    ws.transport.abort()


async def silence(ws):
    pass  # the socket stays open, and nothing more comes


async def release(ws):
    await ws.send(json.dumps({"action": "TELEOP_RELEASE", "robot": ROBOT}))


async def measure(name, end):
    times = []
    for _ in range(RUNS):
        ws = await session()
        await drive(ws)
        since = time.monotonic()
        await end(ws)
        times.append(await first_zero(since))
        await asyncio.sleep(0.35)  # past the watchdog, so runs don't overlap
        try:
            await ws.close()
        except Exception:
            pass
        await asyncio.sleep(0.1)
    worst = max(times)
    print(f"{name:<12} {RUNS} runs: median {statistics.median(times) * 1000:.0f} ms, worst {worst * 1000:.0f} ms", flush=True)
    return worst


async def main():
    await asyncio.sleep(2)  # discovery
    # Five wrong tries would lock out; these are right, so the limit doesn't apply.
    worst = [await measure("socket kill", kill), await measure("silence", silence), await measure("release", release)]
    if max(worst) > LIMIT:
        sys.exit(f"FAIL worst {max(worst) * 1000:.0f} ms is over the {LIMIT * 1000:.0f} ms limit")
    print("PASS watchdog and deadman")


asyncio.run(main())
