"""eval/tools/calibrate.py: you hand-grade 15 answers; agreement with the judge (M8)."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from eval.tools.calibrate import agreement, calibration_ids, grade

ITEMS = [
    {
        "id": f"q{i:03d}",
        "question": f"Q{i}?",
        "reference_answer": "R",
        "answer": f"A{i}",
        "sources": ["s"],
    }
    for i in range(1, 21)
]


def _answers(*values: str) -> Iterator[str]:
    return iter(values)


def test_15_calibration_ids_are_drawn_reproducibly_from_the_sample() -> None:
    sample = [f"q{i:03d}" for i in range(1, 21)]
    ids = calibration_ids(sample, seed=20261010)

    assert ids == calibration_ids(sample, seed=20261010)
    assert len(ids) == len(set(ids)) == 15 and set(ids) <= set(sample)


def test_grading_writes_each_grade_at_once_and_resumes(tmp_path: Path) -> None:
    out = tmp_path / "grades.jsonl"
    feed = _answers(
        "2", "y", "x", "1", "n", "q"
    )  # q001 graded, q002 retried then graded, quit
    grade(ITEMS[:3], out, ask=lambda _prompt: next(feed), show=lambda _text: None)

    assert [json.loads(x) for x in out.read_text().splitlines()] == [
        {"id": "q001", "correctness": 2, "faithful": True},
        {"id": "q002", "correctness": 1, "faithful": False},
    ]
    feed = _answers("0", "n")
    grade(ITEMS[:3], out, ask=lambda _prompt: next(feed), show=lambda _text: None)
    assert [json.loads(x)["id"] for x in out.read_text().splitlines()] == [
        "q001",
        "q002",
        "q003",
    ]


def test_agreement_reports_counts_next_to_rates() -> None:
    human = {"a": (2, True), "b": (1, True), "c": (0, False), "d": (2, False)}
    judge = {"a": (2, True), "b": (2, True), "c": (0, True), "d": (None, None)}

    result = agreement(human, judge)

    assert result["n"] == 3 and result["judge_errors"] == 1
    assert result["correctness_exact"] == {
        "agree": 2,
        "n": 3,
        "rate": pytest.approx(2 / 3),
    }
    assert result["correctness_within_1"] == {"agree": 3, "n": 3, "rate": 1.0}
    assert result["faithful"] == {"agree": 2, "n": 3, "rate": pytest.approx(2 / 3)}
    assert result["confusion"] == {"2->2": 1, "1->2": 1, "0->0": 1}
