"""Stands in for agv-07 and ignores every command: it keeps reporting `driving: true`.

The sims always obey, so this is how a test sees a stop that isn't confirmed. Stop
agv-07 first. Run inside the Styri container; it exits by itself after about 22 s, or
FAKE_SECONDS, and exiting says nothing: to Styri the vehicle is online and silent.
"""

import asyncio
import datetime
import json
import os

import aiomqtt

BASE = {"version": "2.1.0", "manufacturer": "acme", "serialNumber": "SN-0007"}
TOPIC = "uagv/v2/acme/SN-0007"


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def main():
    async with aiomqtt.Client("127.0.0.1") as mqtt:
        await mqtt.publish(f"{TOPIC}/connection", json.dumps(
            {**BASE, "headerId": 0, "timestamp": now(), "connectionState": "ONLINE"}), retain=True, qos=1)
        for n in range(1, int(os.environ.get("FAKE_SECONDS", 22.5)) * 2 + 1):
            await mqtt.publish(f"{TOPIC}/state", json.dumps({
                **BASE, "headerId": n, "timestamp": now(), "orderId": "stuck-1", "orderUpdateId": 0, "lastNodeId": "n1",
                "lastNodeSequenceId": 0, "nodeStates": [{"nodeId": "n2", "sequenceId": 2, "released": True}],
                "edgeStates": [], "driving": True, "actionStates": [], "operatingMode": "AUTOMATIC", "errors": [],
                "batteryState": {"batteryCharge": 71.0, "charging": False},
                "safetyState": {"eStop": "NONE", "fieldViolation": False},
                "agvPosition": {"x": 2.0 + n * 0.02, "y": 2.0, "theta": 0.0, "mapId": "plant-a", "positionInitialized": True}}))
            await asyncio.sleep(0.5)


asyncio.run(main())
