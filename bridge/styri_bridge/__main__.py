"""Entry point: python -m styri_bridge [--fake]"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from . import extensions, system
from .audit import AuditLog
from .config import Config
from .server import BridgeServer

logger = logging.getLogger("styri_bridge")


async def _main(fake: bool) -> None:
    cfg = Config.from_env()
    audit = AuditLog(cfg.audit_db)
    server = BridgeServer(cfg, audit)
    loaded = extensions.load(server)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: stop.done() or stop.set_result(None))

    ros = None
    tasks = []
    if fake:
        from .fake import FakeRobot
        tasks.append(asyncio.create_task(FakeRobot(server.monitor).run()))
        logger.info("Running with FAKE robot (no ROS 2)")
    else:
        from .ros_node import RosRuntime, decode
        ros = RosRuntime(cfg, server.monitor)
        server.decode = decode
        for hook in server.on_ros_node:
            hook(ros.node)
        ros.start()
    tasks.append(asyncio.create_task(system.run(
        lambda v: server.monitor.host_vitals(v["cpu_temperature"], v.get("load_pct")))))

    audit.record("bridge_start", mode="fake" if fake else "ros", extensions=loaded)
    try:
        await server.run(stop)
    finally:
        logger.info("Shutting down Styri...")
        for task in tasks:
            task.cancel()
        if ros:
            ros.shutdown()
        audit.record("bridge_stop")
        audit.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="styri-bridge")
    parser.add_argument("--fake", action="store_true", help="simulate a robot instead of using ROS 2")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    # websockets logs every connection, including each /healthz probe.
    logging.getLogger("websockets").setLevel(logging.WARNING)
    asyncio.run(_main(args.fake))


if __name__ == "__main__":
    main()
