"""eval/tools/rescore.py: re-score stored answers with the current checks, no generation."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.chat import REFUSAL
from eval.tools.rescore import rescore_lines, rescore_run

QUESTIONS = [
    {
        "id": "q001",
        "type": "factoid",
        "answerable": True,
        "question": "How long are readings kept?",
        "reference_answer": "90 days.",
        "gold": [{"doc": "a.md", "span": "kept for ninety days"}],
    },
    {
        "id": "q055",
        "type": "unanswerable",
        "answerable": False,
        "question": "Which payment methods does Nexus accept?",
        "reference_answer": "",
        "gold": [],
    },
]
OLD_CHECKS = {
    "refusal": {"refused": False, "outcome": "missed_refusal", "near_refusal": False},
    "citations": {"valid": 0, "invalid": 0, "validity": None, "cites_gold": None},
    "facts": {"facts": [], "found": [], "share": None},
}


Q001_OLD_CHECKS = {
    "refusal": {"refused": False, "outcome": "answered", "near_refusal": False},
    "citations": {"valid": 1, "invalid": 0, "validity": 1.0, "cites_gold": True},
    "facts": {"facts": ["90"], "found": ["90"], "share": 1.0},
}


def _line(qid: str, qtype: str, text: str, raw: str | None = None) -> dict[str, Any]:
    return {
        "id": qid,
        "type": qtype,
        "answerable": qid != "q055",
        "answer": {
            "text": text,
            "raw_text": text if raw is None else raw,
            "cited": [1] if "[1]" in text else [],
            "dropped": [],
            "refused": text == REFUSAL,
            "sources": ["Readings are kept for ninety days."],
            "error": None,
            "generate_ms": 1.0,
        },
        "checks": Q001_OLD_CHECKS if qid == "q001" else OLD_CHECKS,
    }


LINES = [
    _line("q001", "factoid", "[M6] Ninety days [1]."),
    _line("q055", "unanswerable", "There is no mention of payment in the documents."),
]


def test_stored_answers_get_the_current_checks_and_the_input_is_untouched() -> None:
    before = json.dumps(LINES)

    new = rescore_lines(LINES, QUESTIONS, holdout_ids=[])

    assert json.dumps(LINES) == before
    assert new[1]["checks"]["refusal"]["outcome"] == "near_refusal"
    assert new[0]["checks"]["citations"]["malformed"] == ["[M6]"]
    assert new[0]["checks"]["facts"]["share"] == 1.0
    assert new[0]["answer"]["text"] == LINES[0]["answer"]["text"]


def test_reclean_reruns_the_apps_cleanup_on_the_raw_output() -> None:
    raw = "<answer>\nNinety days [1]RIGHT [7].\n</answer>"
    lines = [_line("q001", "factoid", raw, raw=raw)]

    new = rescore_lines(lines, QUESTIONS, holdout_ids=[], reclean=True)

    answer = new[0]["answer"]
    assert answer["text"] == "Ninety days [1] RIGHT."
    assert (answer["cited"], answer["dropped"]) == ([1], [7])
    assert answer["refused"] is False
    assert new[0]["checks"]["citations"]["malformed"] == ["[1]RIGHT"]


def test_a_holdout_line_is_refused() -> None:
    with pytest.raises(SystemExit, match="hold-out"):
        rescore_lines(LINES, QUESTIONS, holdout_ids=["q055"])


def test_a_run_is_rescored_into_a_new_file_next_to_the_untouched_results(
    tmp_path: Path,
) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text("".join(json.dumps(x) + "\n" for x in LINES))
    (tmp_path / "summary.json").write_text(
        json.dumps({"generation": {"near_refusal": 0}, "generation_per_type": {}})
    )
    before = results.read_bytes()

    report = rescore_run(tmp_path, QUESTIONS, holdout_ids=[])

    assert results.read_bytes() == before
    saved = json.loads((tmp_path / "rescore.json").read_text())
    assert saved == report
    assert report["old"]["generation"] == {"near_refusal": 0}
    assert report["checks_fixed"]["generation"]["near_refusal"] == 1
    assert report["checks_fixed_and_recleaned"]["generation"]["n"] == 2
    assert report["changed"]["checks_fixed"] == {
        "q001": ["citations.malformed"],
        "q055": ["refusal.outcome", "refusal.near_refusal"],
    }
