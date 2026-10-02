#!/usr/bin/env python3
"""PostToolUse: auto-fix and format the file Claude just wrote, if it's Python."""

import json
import subprocess
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path = payload.get("tool_input", {}).get("file_path")
    if not file_path or not file_path.endswith(".py"):
        return 0

    subprocess.run(
        ["uv", "run", "ruff", "check", "--fix", "--quiet", file_path], check=False
    )
    subprocess.run(["uv", "run", "ruff", "format", "--quiet", file_path], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
