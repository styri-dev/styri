"""Run a real bridge on a free port for end-to-end tests of the server."""

import asyncio
import json
import socket

from websockets.asyncio.client import connect

from styri_bridge.audit import AuditLog
from styri_bridge.config import Config
from styri_bridge.server import BridgeServer

BROADCASTS = {"event", "snapshot"}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_bridge(test, ui_dir=None, setup=None):
    """Start a bridge, run `await test(url, server, audit)`, stop it. Returns the audit log."""
    cfg = Config(host="127.0.0.1", port=free_port(), audit_db=":memory:", ui_dir=ui_dir, robot_name="test-bot")
    audit = AuditLog(":memory:")
    server = BridgeServer(cfg, audit)
    if setup:
        setup(server)

    async def main():
        stop = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(server.run(stop))
        url = f"ws://127.0.0.1:{cfg.port}/ws"
        for _ in range(50):  # wait for the listener
            try:
                async with connect(url):
                    break
            except OSError:
                await asyncio.sleep(0.02)
        try:
            await test(url, server, audit)
        finally:
            stop.set_result(None)
            await task

    asyncio.run(main())
    return audit


async def recv_reply(ws, timeout=2):
    """Next direct reply, skipping the live broadcasts every client gets."""
    async def wait():
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("type") not in BROADCASTS:
                return msg
    return await asyncio.wait_for(wait(), timeout)


async def recv_type(ws, kind, timeout=3):
    async def wait():
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == kind:
                return msg
    return await asyncio.wait_for(wait(), timeout)


async def connect_panel(url, **kwargs):
    ws = await connect(url, **kwargs)
    assert json.loads(await ws.recv())["type"] == "hello"
    assert json.loads(await ws.recv())["type"] == "activity"
    return ws


async def send(ws, **msg):
    await ws.send(json.dumps(msg))
