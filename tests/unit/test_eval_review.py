"""eval/tools/review.py: keep / edit / reject each candidate; only kept ones reach v1.jsonl."""

import io
import json
from pathlib import Path

from eval.tools import review


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


CANDIDATES = [
    {
        "id": "q001",
        "type": "factoid",
        "question": "Q one?",
        "gold": [{"doc": "a.md", "span": "s1"}],
        "gold_mode": "any",
        "reference_answer": "r1",
        "answerable": True,
    },
    {
        "id": "q002",
        "type": "factoid",
        "question": "Q two?",
        "gold": [{"doc": "a.md", "span": "s2"}],
        "gold_mode": "any",
        "reference_answer": "r2",
        "answerable": True,
    },
    {
        "id": "q003",
        "type": "unanswerable",
        "question": "Q three?",
        "gold": [],
        "gold_mode": "any",
        "reference_answer": "none",
        "answerable": False,
    },
]


def test_keep_edit_reject_and_resume(tmp_path: Path) -> None:
    candidates, out = tmp_path / "candidates.jsonl", tmp_path / "v1.jsonl"
    _write(candidates, CANDIDATES)
    # q001 keep; q002 edit the question (blank lines keep the span and answer); q003 reject.
    answers = io.StringIO("k\ne\nQ two, reworded?\n\n\nr\n")

    review.main([str(candidates), str(out)], stdin=answers, stdout=io.StringIO())

    kept = [json.loads(line) for line in out.read_text().splitlines()]
    assert [q["id"] for q in kept] == ["q001", "q002"]
    assert kept[1]["question"] == "Q two, reworded?"
    assert kept[1]["edited"] is True and kept[0]["edited"] is False
    decisions = json.loads((tmp_path / "v1.decisions.json").read_text())
    assert decisions == {"q001": "keep", "q002": "edit", "q003": "reject"}

    # Running again resumes: nothing left to ask, output unchanged.
    review.main(
        [str(candidates), str(out)], stdin=io.StringIO(""), stdout=io.StringIO()
    )
    assert [json.loads(line)["id"] for line in out.read_text().splitlines()] == [
        "q001",
        "q002",
    ]
