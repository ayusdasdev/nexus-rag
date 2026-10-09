import re
from functools import lru_cache
from pathlib import Path

# Prompts live as Markdown files in app/prompts/ and are read on first use, not at import.
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_NAME = re.compile(r"[a-z][a-z0-9_]*")


@lru_cache
def load_prompt(name: str) -> str:
    """Return app/prompts/<name>.md. name is a bare identifier, never a path."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"invalid prompt name: {name!r}")
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
