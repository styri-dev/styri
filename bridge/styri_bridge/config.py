"""Runtime configuration: environment variables, plus the topic mapping.

The same image works on any robot. Simple robots need only environment
variables (`docker run -e ROS_DOMAIN_ID=7 -e STYRI_ROBOT_NAME=amr-01 …`);
anything else is described in a styri.yaml file (see mapping.py), loaded
from STYRI_CONFIG or /etc/styri/styri.yaml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import mapping


def _env_mapping() -> mapping.Loaded:
    return mapping.Loaded((mapping.from_env(),), "environment")


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    audit_db: str = "/var/lib/styri/audit.db"
    # The built operator UI, served on the same port as the WebSocket.
    ui_dir: str | None = "/opt/styri/ui"
    # Which topics and fields feed the panel, and where that came from.
    mapping: mapping.Loaded = field(default_factory=_env_mapping)
    # Shown in the header. Defaults to the file's robot name, then the hostname.
    robot_name: str | None = None

    def __post_init__(self):
        if self.robot_name is None:
            object.__setattr__(self, "robot_name", self.robot.name)

    @property
    def robot(self) -> mapping.RobotMap:
        """The robot Styri Core shows: the only one, or the first of a list."""
        return self.mapping.robots[0]

    @property
    def stale_after(self) -> float:
        return self.robot.stale_after

    @property
    def min_voltage(self) -> float | None:
        v = self.robot.value("voltage")
        return v.rule.warn_below if v else None

    @classmethod
    def from_env(cls, config_file: str | None = None) -> "Config":
        env = os.environ.get
        return cls(
            host=env("STYRI_HOST", cls.host),
            port=int(env("STYRI_PORT", cls.port)),
            audit_db=env("STYRI_AUDIT_DB", cls.audit_db),
            ui_dir=env("STYRI_UI_DIR", cls.ui_dir) or None,
            mapping=mapping.load(config_file),
        )
