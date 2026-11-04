"""Every suite's setup: no robot paused, no task running, whatever ran before.

Stop all leaves VDA 5050 vehicles paused, on purpose: Styri never unpauses by itself.
Here a test does, as an operator would. Does nothing with control off.
"""

import asyncio
import json
import os
import sys
import time

from websockets.asyncio.client import connect

PASSWORD = os.environ.get("STYRI_ADMIN_PASSWORD", "styri-demo")
SETTLE = 2.2  # past an Operator stop's hold, and the limit on anonymous stops


async def main():
    deadline = time.monotonic() + 60
    while True:
        try:
            ws = await connect("ws://127.0.0.1:8080/ws", origin="http://127.0.0.1:8080")
            break
        except OSError:
            if time.monotonic() > deadline:
                sys.exit("FAIL the panel didn't come up in 60 s")
            await asyncio.sleep(0.5)
    robots: list = []
    hello = None

    async def listen():
        nonlocal robots, hello
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "hello":
                hello = msg
            elif msg["type"] == "fleet":
                robots = msg["robots"]

    task = asyncio.create_task(listen())
    while hello is None:
        await asyncio.sleep(0.05)
    if not hello.get("control"):
        return
    await ws.send(json.dumps({"action": "LOGIN", "password": PASSWORD}))

    def dirty():
        return [r for r in robots if r["stale"] or r["paused"] or r["task"]["state"] in ("active", "paused") or r["driving"]]

    while time.monotonic() < deadline:
        await asyncio.sleep(1.2)  # a fresh fleet message
        if robots and not dirty():
            break
        for r in dirty():
            if r["task"]["state"] in ("active", "paused") and r["capabilities"]["can_cancel"]:
                await ws.send(json.dumps({"action": "CANCEL", "robot": r["id"]}))
            if r["paused"] and r["capabilities"]["can_pause"]:
                await ws.send(json.dumps({"action": "RESUME", "robot": r["id"]}))
    else:
        sys.exit(f"FAIL robots wouldn't settle: {[r['name'] for r in dirty()]}")
    await asyncio.sleep(SETTLE)
    task.cancel()
    await ws.close()
    print("Clean: nothing paused, no task running")


asyncio.run(main())
