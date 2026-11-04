"""Check VDA 5050 messages against the official JSON schemas in schemas/."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).parent / "schemas"
TOPICS = ("connection", "factsheet", "instantActions", "order", "state", "visualization")


@cache
def _validator(topic: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / f"{topic}.schema").read_text(encoding="utf-8")))


def problems(topic: str, message: object, limit: int = 3) -> list[str]:
    """What's wrong with a message, in short lines. Empty when it's valid."""
    out = []
    for error in _validator(topic).iter_errors(message):
        where = ".".join(str(p) for p in error.absolute_path) or "message"
        out.append(f"{where}: {error.message[:120]}")
        if len(out) == limit:
            break
    return out
