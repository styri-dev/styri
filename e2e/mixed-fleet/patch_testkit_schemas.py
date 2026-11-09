"""Correct three defects in VDA 5050's 2.0.0 tag schemas, as the testkit corrects others.

The 2.0.0 tag's schemas disagree with the 2.0 text, which the specification says wins.
VDA 5050's own release/2.0.0 branch (commit 9c45639) has the corrections applied here:

  1. instantActions: actions name their type in `actionType`, not `actionName`
     (the tag's own order and state schemas already say actionType).
  2. order: `allowedDeviationXY`, not `allowedDeviationXy`.
  3. state: `theta` is optional in nodeStates[].nodePosition.

Usage: python3 patch_testkit_schemas.py <testkit source folder>. A copy of
styri-vda-bench's build/patch_schemas.py: change both. Fails loudly if a schema
no longer has what it corrects, so a new testkit pin can't skip it silently.
"""

import json
import sys
from pathlib import Path

ROOT = "vda5050-conformance/src/main/resources/io/github/ksshen0000/vda5050/conformance/schemas/2.0.0"


def rename(node, old, new):
    """Rename a property and its `required` entry, everywhere in the schema. Returns how many."""
    count = 0
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and old in props:
            node["properties"] = {new if k == old else k: v for k, v in props.items()}
            node["required"] = [new if r == old else r for r in node.get("required", [])]
            count += 1
        for v in node.values():
            count += rename(v, old, new)
    elif isinstance(node, list):
        for v in node:
            count += rename(v, old, new)
    return count


def main(src: str) -> None:
    folder = Path(src) / ROOT
    load = lambda name: json.loads((folder / f"{name}.schema").read_text(encoding="utf-8"))  # noqa: E731
    save = lambda name, s: (folder / f"{name}.schema").write_text(json.dumps(s, indent=4) + "\n", encoding="utf-8")  # noqa: E731

    s = load("instantActions")
    assert rename(s, "actionName", "actionType") == 1, "instantActions: no actionName to correct"
    save("instantActions", s)

    s = load("order")
    assert rename(s, "allowedDeviationXy", "allowedDeviationXY") == 1, "order: no allowedDeviationXy to correct"
    save("order", s)

    s = load("state")
    position = s["properties"]["nodeStates"]["items"]["properties"]["nodePosition"]
    assert "theta" in position["required"], "state: nodePosition theta is already optional"
    position["required"] = [r for r in position["required"] if r != "theta"]
    save("state", s)
    print("Corrected the 2.0.0 schemas: actionType, allowedDeviationXY, optional nodeStates theta")


if __name__ == "__main__":
    main(sys.argv[1])
