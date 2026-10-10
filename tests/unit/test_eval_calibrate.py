"""eval/tools/calibrate.py: you hand-grade 15 answers; agreement with the judge (M8)."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from eval.dataset import DATASETS, load_questions
from eval.judge import judge_sample
from eval.tools.calibrate import agreement, calibration_ids, calibration_items, grade

SPLIT = json.loads((DATASETS / "v1.split.json").read_text())

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


# --- the 15 to grade, before the judge has run ----------------------------------------


def _run_lines(ids: list[str]) -> list[dict[str, object]]:
    return [
        {
            "id": i,
            "answer": {"text": f"answer {i}", "sources": [f"source {i}"]},
            "checks": {"refusal": {"outcome": "answered"}},
        }
        for i in ids
    ]


def test_the_15_come_from_the_fixed_judge_sample_and_need_no_verdict() -> None:
    questions = load_questions()
    sample = judge_sample(questions, SPLIT["dev"])

    items = calibration_items(questions, SPLIT, _run_lines(SPLIT["dev"]))

    ids = [x["id"] for x in items]
    assert ids == calibration_ids(sample, seed=20261010)
    assert set(ids) <= set(sample) <= set(SPLIT["dev"])
    assert not set(ids) & set(SPLIT["holdout"])
    by_id = {q["id"]: q for q in questions}
    first = items[0]
    assert first["question"] == by_id[first["id"]]["question"]
    assert first["reference_answer"] == by_id[first["id"]].get("reference_answer", "")
    assert first["answer"] == f"answer {first['id']}"
    assert first["sources"] == [f"source {first['id']}"]


def test_the_grader_sees_no_checks_or_verdicts() -> None:
    lines = _run_lines(SPLIT["dev"])
    for line in lines:
        line["answer"]["verdict"] = {"correctness": 2}  # type: ignore[index]

    items = calibration_items(load_questions(), SPLIT, lines)

    assert {tuple(sorted(x)) for x in items} == {
        ("answer", "id", "question", "reference_answer", "sources")
    }


def test_a_run_missing_a_sampled_answer_is_refused() -> None:
    lines = _run_lines(SPLIT["dev"][:10])

    with pytest.raises(SystemExit, match="no answer"):
        calibration_items(load_questions(), SPLIT, lines)
