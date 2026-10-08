#!/usr/bin/env python3
"""Stop hook: block ending the turn while `make test` is failing."""

import json
import subprocess
import sys

_MAX_CHARS = 3000


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}

    if payload.get("stop_hook_active"):
        return 0

    result = subprocess.run(
        ["make", "test"],
        cwd=payload.get("cwd"),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return 0

    output = result.stdout + result.stderr
    print(output[-_MAX_CHARS:], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
