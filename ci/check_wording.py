#!/usr/bin/env python3
"""Fail if a banned stop term appears anywhere in the repo.

It's "Operator stop" everywhere. The one sentence allowed to use the term is the
disclaimer below; the only other exception is VDA 5050's own schema field, in the
official schema files and the one line that reads it.
"""

import re
import subprocess
import sys
from pathlib import Path

BANNED = re.compile(r"e[-_ ]?stop|emergency[-_ ]stop", re.IGNORECASE)
DISCLAIMER = "Operator stop is a software stop. It is not an emergency stop or a safety function."
SCHEMA_DIR = "bridge/styri_bridge/vda/schemas/"
SCHEMA_FIELD = '"eStop"'  # exactly the schema's key, quoted
# "e stop" also matches inside ordinary words and code.
WORD = re.compile(r"(?<![a-z])(" + BANNED.pattern + r")(?![a-z])", re.IGNORECASE)
SKIP = (".png", ".gif", ".woff2", ".lock", ".ico", ".jpg")


def problems(root: Path) -> list[str]:
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout.split("\n")
    out = []
    for name in filter(None, tracked):
        if name.startswith(SCHEMA_DIR) or name.endswith(SKIP) or name == "ci/check_wording.py":
            continue
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            clean = line.replace(DISCLAIMER, "").replace(SCHEMA_FIELD, "")
            if WORD.search(clean):
                out.append(f"{name}:{n}: {line.strip()[:100]}")
    return out


def main() -> int:
    found = problems(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
    for line in found:
        print(line)
    if found:
        print(f"\n{len(found)} line(s) use a banned term. Write \"Operator stop\". The only allowed use is: {DISCLAIMER}")
        return 1
    print("Wording OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
