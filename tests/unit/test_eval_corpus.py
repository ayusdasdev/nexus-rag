"""The frozen M8 corpus never changes silently: every file matches its manifest hash."""

import hashlib
import json
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[2] / "eval" / "corpus"


def test_every_corpus_file_matches_the_manifest_and_nothing_extra_is_there() -> None:
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    listed = {entry["file"]: entry["sha256"] for entry in manifest["files"]}
    present = {p.name for p in CORPUS.iterdir() if p.name != "manifest.json"}

    assert present == set(listed)
    for name, sha in listed.items():
        assert hashlib.sha256((CORPUS / name).read_bytes()).hexdigest() == sha, name
    assert len(listed) == 22
