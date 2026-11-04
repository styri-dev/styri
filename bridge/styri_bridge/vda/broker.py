"""The bundled Mosquitto: started by Styri, for the site's vehicles only.

It listens on localhost, anonymously, for Styri itself. With `vda.broker.bind`
it also listens on that LAN address, where each vehicle logs in with its own
username and may touch only its own topics. It never bridges to another broker:
nothing here writes a `connection` or `address` line.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..mapping import Broker, RobotMap

logger = logging.getLogger("styri_bridge")

RESTART_AFTER = 2.0  # seconds


def config(broker: Broker, interface: str, robots: list[RobotMap], folder: str) -> str:
    """mosquitto.conf, for a folder that holds its password and ACL files."""
    lines = ["per_listener_settings true", "persistence false", "log_dest stdout", "log_type error", "log_type warning",
             f"listener {broker.port} 127.0.0.1", "allow_anonymous true"]
    if broker.bind:
        lines += [f"listener {broker.port} {broker.bind}", "allow_anonymous false",
                  f"password_file {folder}/passwords", f"acl_file {folder}/acl"]
        if broker.tls_cert:
            lines += [f"certfile {broker.tls_cert}", f"keyfile {broker.tls_key}"]
    return "\n".join(lines) + "\n"


def acl(interface: str, robots: list[RobotMap]) -> str:
    """Each vehicle may use its own topics, and no one else's."""
    entries = []
    for r in robots:
        if r.link.username:
            entries += [f"user {r.link.username}",
                        f"topic readwrite {interface}/+/{r.link.manufacturer}/{r.link.serial}/#", ""]
    return "\n".join(entries)


class BundledBroker:
    def __init__(self, broker: Broker, interface: str, robots: list[RobotMap], activity, env: dict | None = None):
        self.broker, self.interface, self.activity = broker, interface, activity
        self.robots = [r for r in robots if r.link.protocol == "vda5050"]
        self.env = os.environ if env is None else env
        self.folder: str | None = None

    def available(self) -> bool:
        return shutil.which("mosquitto") is not None

    def _write(self) -> str:
        self.folder = tempfile.mkdtemp(prefix="styri-mqtt-")
        folder = Path(self.folder)
        (folder / "acl").write_text(acl(self.interface, self.robots), encoding="utf-8")
        passwords = folder / "passwords"
        passwords.touch(mode=0o600)
        for r in self.robots:
            password = self.env.get(r.link.password_env or "")
            if r.link.username and password:
                # The password goes through a file, so it never shows in a process list.
                batch = folder / "batch"
                batch.touch(mode=0o600)
                batch.write_text(f"{r.link.username}:{password}\n", encoding="utf-8")
                subprocess.run(["mosquitto_passwd", "-U", str(batch)], check=True, capture_output=True)
                with passwords.open("a", encoding="utf-8") as out:
                    out.write(batch.read_text(encoding="utf-8"))
                batch.unlink()
            elif self.broker.bind:
                self.activity.add("warning", f"{r.name}: no broker password (set username and password_env), "
                                             "so it can't log in over the LAN", "broker")
        conf = folder / "mosquitto.conf"
        conf.write_text(config(self.broker, self.interface, self.robots, self.folder), encoding="utf-8")
        return str(conf)

    async def run(self) -> None:
        """Keep the broker up. A failure is reported, and never takes the panel down."""
        if not self.available():
            self.activity.add("warning", "Bundled broker not started: Mosquitto isn't installed here", "broker")
            return
        conf = self._write()
        reported = False
        while True:
            proc = await asyncio.create_subprocess_exec("mosquitto", "-c", conf, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT)
            try:
                out, _ = await proc.communicate()
            except asyncio.CancelledError:
                proc.terminate()
                await proc.wait()
                shutil.rmtree(self.folder, ignore_errors=True)
                raise
            text = out.decode(errors="replace").strip()
            logger.warning("Bundled broker exited (%s): %s", proc.returncode, text[-300:])
            if not reported:
                reported = True
                self.activity.add("warning", f"Bundled broker stopped: port {self.broker.port} may be in use. "
                                             "VDA 5050 robots won't connect until it's free", "broker")
            await asyncio.sleep(RESTART_AFTER)
