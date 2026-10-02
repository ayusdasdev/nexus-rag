#!/usr/bin/env python3
"""PreToolUse guard: block edits to real .env files and to committed migrations."""

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path = payload.get("tool_input", {}).get("file_path")
    if not file_path:
        return 0

    path = Path(file_path)

    if path.name == ".env":
        print(
            f"Blocked: {file_path} is a secrets file. Edit .env.example instead, "
            "or edit .env by hand outside Claude Code.",
            file=sys.stderr,
        )
        return 2

    if "alembic/versions/" in path.as_posix():
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            print(
                f"Blocked: {file_path} is a committed migration. "
                "Committed migrations are immutable, create a new migration.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
