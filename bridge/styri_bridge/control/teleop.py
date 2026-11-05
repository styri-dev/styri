"""Hold-to-drive: one driver per robot, and the watchdog.

The bridge holds the watchdog, not the browser. It runs in its own thread, so a
busy event loop can't delay it. A closed connection stops the robot at once; a
silent one stops it when TELEOP messages have been missing for GAP seconds.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("styri_bridge")

GAP = 0.3     # seconds without a TELEOP message before the robot is stopped (limit: 0.5)
PERIOD = 0.02  # how often the watchdog looks


@dataclass
class Drive:
    session: object
    last: float
    send: Callable[[float, float], None]
    on_end: Callable[[str], None]


class Teleop:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._drives: dict[int, Drive] = {}  # robot index -> who's driving
        self._running = False

    def driver(self, robot: int) -> object | None:
        with self._lock:
            drive = self._drives.get(robot)
            return drive.session if drive else None

    def drive(self, robot: int, session: object, linear: float, angular: float,
              send: Callable[[float, float], None], on_end: Callable[[str], None]) -> bool:
        """Forward one held command. False when someone else is driving; the first one starts the drive."""
        with self._lock:
            drive = self._drives.get(robot)
            if drive is not None and drive.session is not session:
                return False
            if drive is None:
                self._drives[robot] = Drive(session, self.clock(), send, on_end)
            else:
                drive.last = self.clock()
            send(linear, angular)
        return True

    def release(self, robot: int, reason: str, session: object | None = None) -> bool:
        """Zero velocity now, and free the lock. With a session, only if it's the driver."""
        with self._lock:
            drive = self._drives.get(robot)
            if drive is None or (session is not None and drive.session is not session):
                return False
            del self._drives[robot]
            drive.send(0.0, 0.0)
        drive.on_end(reason)
        return True

    def disconnected(self, session: object) -> None:
        with self._lock:
            robots = [r for r, d in self._drives.items() if d.session is session]
        for robot in robots:
            self.release(robot, "connection_closed", session)

    def check(self) -> None:
        """One watchdog pass."""
        now = self.clock()
        with self._lock:
            late = [r for r, d in self._drives.items() if now - d.last > GAP]
        for robot in late:
            self.release(robot, "watchdog")

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._watch, name="teleop-watchdog", daemon=True).start()

    def stop_all(self, reason: str) -> None:
        with self._lock:
            robots = list(self._drives)
        for robot in robots:
            self.release(robot, reason)

    def stop(self) -> None:
        self._running = False
        self.stop_all("shutdown")

    def _watch(self) -> None:
        while self._running:
            time.sleep(PERIOD)
            try:
                self.check()
            except Exception:  # the watchdog must outlive anything a sink does
                logger.exception("teleop watchdog")
