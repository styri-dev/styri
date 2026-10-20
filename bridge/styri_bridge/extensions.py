"""Extension point for editions built on Styri Core.

An extension is a function `register(bridge)` exposed through the
`styri.extensions` entry-point group. It may add WebSocket actions, HTTP
routes, hello fields, connect/disconnect hooks, background tasks and ROS
setup through the `BridgeServer` methods it receives.

Styri Core itself ships no extensions and is read-only: with none
installed, the bridge creates no ROS publishers or services.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

logger = logging.getLogger("styri_bridge")

GROUP = "styri.extensions"


def load(bridge) -> list[str]:
    """Register every installed extension. Returns their names."""
    names = []
    for ep in entry_points(group=GROUP):
        register = ep.load()
        register(bridge)
        names.append(ep.name)
        logger.warning("Loaded extension %r from %s", ep.name, ep.value)
    return names
