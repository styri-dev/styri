"""Fresh-machine quickstart check: within 60 s of starting, http://localhost:8080
serves the panel and its WebSocket carries live data from the robot.

Needs only Docker; runs inside the Styri image (which has websockets):
  docker run --rm --network host -v "$PWD/ci:/ci:ro" --entrypoint python3 \
    ghcr.io/styri-dev/styri-core:<tag> /ci/quickstart_check.py
"""

import asyncio
import json
import sys
import time
import urllib.request

from websockets.asyncio.client import connect

BASE = "http://localhost:8080"
DEADLINE = time.monotonic() + 60


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


async def main() -> None:
    while True:  # the panel itself
        try:
            html = urllib.request.urlopen(BASE + "/", timeout=2).read().decode()
            if "<title>Styri</title>" in html:
                break
        except OSError:
            pass
        if time.monotonic() > DEADLINE:
            fail("no panel at http://localhost:8080 within 60 s")
        await asyncio.sleep(1)
    print(f"panel served after {60 - (DEADLINE - time.monotonic()):.1f} s")

    async with connect(BASE.replace("http", "ws") + "/ws", origin=BASE) as ws:
        while time.monotonic() < DEADLINE:
            msg = json.loads(await asyncio.wait_for(ws.recv(), max(1.0, DEADLINE - time.monotonic())))
            if msg.get("type") != "snapshot":
                continue
            live = [t for t in msg["topics"] if t["age"] is not None and not t["stale"]]
            battery = msg["battery"]["value"]
            if msg["robot_found"] and battery is not None and live:
                print(f"live data after {60 - (DEADLINE - time.monotonic()):.1f} s: health={msg['health']['level']}, "
                      f"battery={battery:.0f} %, {len(live)} live topics")
                return
    fail("panel never showed live robot data within 60 s")


asyncio.run(main())
