"""With control off, nothing is published to MQTT, and commands are refused.

Run inside the Styri container, with e2e/mixed-fleet/view-only.yaml.
"""

import asyncio
import json
import sys
import time

import aiomqtt
from websockets.asyncio.client import connect

COMMANDS = ("instantActions", "order")


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


async def main():
    await wait_for_panel()
    seen, vehicles = [], set()
    async with aiomqtt.Client("127.0.0.1") as mqtt:
        await mqtt.subscribe("uagv/#")

        async def listen():
            async for message in mqtt.messages:
                parts = str(message.topic).split("/")
                vehicles.add(parts[3])
                if parts[-1] in COMMANDS:
                    seen.append(str(message.topic))

        task = asyncio.create_task(listen())
        async with connect("ws://127.0.0.1:8080/ws", origin="http://127.0.0.1:8080") as ws:
            for msg in ({"action": "OPERATOR_STOP_ALL"}, {"action": "GOAL", "robot": "agv-07", "node": "n3"},
                        {"action": "PAUSE", "robot": "agv-08"}):
                await ws.send(json.dumps(msg))
            await asyncio.sleep(15)  # longer than a factsheet retry
        task.cancel()
    if len(vehicles) < 2:
        sys.exit(f"FAIL expected both vehicles on the broker, saw {vehicles}")
    if seen:
        sys.exit(f"FAIL view-only published: {seen[:5]}")
    print("PASS view-only sent nothing over MQTT")


asyncio.run(main())
