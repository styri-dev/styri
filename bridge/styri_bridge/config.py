"""Runtime configuration, read from environment variables.

Everything is env-driven so the same image works on any robot:
`docker run -e ROS_DOMAIN_ID=7 -e STYRI_ROBOT_NAME=amr-01 …`.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    audit_db: str = "/var/lib/styri/audit.db"
    # Shown in the header. Defaults to the machine's hostname.
    robot_name: str = field(default_factory=socket.gethostname)
    # The built operator UI, served on the same port as the WebSocket.
    ui_dir: str | None = "/opt/styri/ui"
    # Topics the Overview reads. Point these at your robot's names.
    battery_topic: str = "/battery_state"
    diagnostics_topic: str = "/diagnostics"
    # A topic that has been publishing counts as stale after this long.
    stale_after: float = 5.0
    # Optional low-voltage warning (volts). Unset: voltage is shown, never judged.
    min_voltage: float | None = None

    @classmethod
    def from_env(cls) -> "Config":
        env = os.environ.get
        return cls(
            host=env("STYRI_HOST", cls.host),
            port=int(env("STYRI_PORT", cls.port)),
            audit_db=env("STYRI_AUDIT_DB", cls.audit_db),
            robot_name=env("STYRI_ROBOT_NAME") or socket.gethostname(),
            ui_dir=env("STYRI_UI_DIR", cls.ui_dir) or None,
            battery_topic=env("STYRI_BATTERY_TOPIC", cls.battery_topic),
            diagnostics_topic=env("STYRI_DIAGNOSTICS_TOPIC", cls.diagnostics_topic),
            stale_after=float(env("STYRI_STALE_AFTER", cls.stale_after)),
            min_voltage=float(env("STYRI_MIN_VOLTAGE")) if env("STYRI_MIN_VOLTAGE", "").strip() else None,
        )
