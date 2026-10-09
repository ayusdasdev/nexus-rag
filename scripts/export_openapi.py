"""Write the API contract to docs/openapi.json (make openapi). A unit test fails if it's stale."""

import json
from pathlib import Path

from app.main import create_app

OUT = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"

OUT.write_text(
    json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"wrote {OUT}")
