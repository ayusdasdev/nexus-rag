"""Every tracked file that starts with a shebang is executable in git (mode 100755).

ruff's EXE001 doesn't run on WSL, where file modes are unreliable, so a missing executable bit
passed `make lint` locally and failed it in CI. This checks the committed mode instead.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _tracked() -> list[tuple[str, str]]:
    """(mode, path) for every tracked file, from the index (git ls-files -s)."""
    out = subprocess.run(
        ["git", "ls-files", "-s", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode()
    entries = []
    for record in out.split("\0"):
        if record:
            meta, path = record.split("\t", 1)
            entries.append((meta.split()[0], path))
    return entries


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="not a git checkout")
def test_every_tracked_shebang_file_is_executable_in_git() -> None:
    shebang_files = {
        path: mode
        for mode, path in _tracked()
        if (ROOT / path).is_file() and (ROOT / path).read_bytes()[:2] == b"#!"
    }

    assert shebang_files
    not_executable = sorted(p for p, mode in shebang_files.items() if mode != "100755")
    assert not_executable == [], "run: git update-index --chmod=+x <file>"
