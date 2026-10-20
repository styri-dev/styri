"""Messages a browser may send. Styri Core is read-only: there are two."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass


class ProtocolError(ValueError):
    """The message is not one Styri understands."""


@dataclass(frozen=True)
class Ping:
    """Round-trip probe for the link latency tile."""
    t: float


@dataclass(frozen=True)
class Select:
    """Ask for the latest message on one topic (Topics tab)."""
    topic: str


def parse(raw: str | bytes) -> tuple[str, dict]:
    """Decode a message into (action, payload) without interpreting it."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError("malformed JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("action"), str):
        raise ProtocolError("message must be a JSON object with an action")
    return data["action"], data


def ping(data: dict) -> Ping:
    t = data.get("t", 0)
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
        raise ProtocolError("'t' must be a finite number")
    return Ping(float(t))


def select(data: dict) -> Select:
    topic = data.get("topic")
    if not isinstance(topic, str) or not topic or len(topic) > 256:
        raise ProtocolError("'topic' must be a topic name")
    return Select(topic)
