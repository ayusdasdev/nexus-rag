"""eval/tools/judge_run.py: the one-call judge over the fixed 20-question sample of a stored
generation run, one verdict line written per call, resumable. FakeLLM only (M8)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.providers.llm import FakeLLM
from eval.dataset import DATASETS, load_questions
from eval.judge import judge_sample
from eval.tools.judge_run import check_provider, judge_run, rough_scores

SPLIT = json.loads((DATASETS / "v1.split.json").read_text())
QUESTIONS = load_questions()
SAMPLE = judge_sample(QUESTIONS, SPLIT["dev"])
GOOD = '{"correctness": 2, "faithful": true, "unsupported_claims": []}'


def _run_dir(tmp_path: Path, ids: list[str]) -> Path:
    lines = [
        {
            "id": i,
            "answer": {
                "text": f"answer {i} [1]",
                "raw_text": f"answer {i} [1]",
                "cited": [1],
                "dropped": [],
                "sources": [f"source {i}"],
            },
        }
        for i in ids
    ]
    (tmp_path / "results.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in lines)
    )
    return tmp_path


def _judge(run_dir: Path, llm: FakeLLM) -> list[dict[str, Any]]:
    return asyncio.run(judge_run(run_dir, QUESTIONS, SPLIT, llm))


def test_every_sample_answer_is_judged_once_and_written_as_it_finishes(
    tmp_path: Path,
) -> None:
    run_dir = _run_dir(tmp_path, SPLIT["dev"])
    llm = FakeLLM([GOOD])

    verdicts = _judge(run_dir, llm)

    assert [v["id"] for v in verdicts] == SAMPLE
    assert len(llm.calls) == 20
    saved = [json.loads(x) for x in (run_dir / "judge.jsonl").read_text().splitlines()]
    assert saved == verdicts
    assert saved[0]["correctness"] == 2 and saved[0]["raw"] == GOOD
    assert saved[0]["ms"] >= 0
    # The judge saw the stored answer and its sources, nothing from the grades.
    user = llm.calls[0][1].content
    assert f"answer {SAMPLE[0]} [1]" in user and f"source {SAMPLE[0]}" in user


def test_a_rerun_skips_the_verdicts_already_written(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, SPLIT["dev"])
    first = [
        json.dumps({"id": i, "correctness": 1, "faithful": True}) for i in SAMPLE[:7]
    ]
    (run_dir / "judge.jsonl").write_text("\n".join(first) + "\n")
    llm = FakeLLM([GOOD])

    verdicts = _judge(run_dir, llm)

    assert len(llm.calls) == 13
    assert [v["id"] for v in verdicts] == SAMPLE
    assert [v["correctness"] for v in verdicts[:7]] == [1] * 7


def test_a_missing_sample_answer_stops_before_any_call(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, SAMPLE[1:])
    llm = FakeLLM([GOOD])

    with pytest.raises(SystemExit, match="no answer"):
        _judge(run_dir, llm)
    assert llm.calls == []


def test_a_holdout_id_in_the_sample_is_refused(tmp_path: Path) -> None:
    split = {"dev": SPLIT["dev"], "holdout": [SAMPLE[0]]}

    with pytest.raises(SystemExit, match="hold-out"):
        asyncio.run(
            judge_run(_run_dir(tmp_path, SPLIT["dev"]), QUESTIONS, split, FakeLLM([]))
        )


def test_the_judge_runs_on_ollama_only() -> None:
    check_provider(Settings(llm_provider="ollama"))
    with pytest.raises(SystemExit, match="ollama only"):
        check_provider(Settings.model_construct(llm_provider="anthropic"))


def test_rough_scores_are_counts_with_errors_apart() -> None:
    answerable = {"a": True, "b": True, "c": False, "d": True}
    verdicts: list[dict[str, Any]] = [
        {"id": "a", "correctness": 2, "faithful": True, "error": None},
        {"id": "b", "correctness": 1, "faithful": False, "error": None},
        {"id": "c", "correctness": 0, "faithful": True, "error": None},
        {"id": "d", "correctness": None, "faithful": None, "error": "unparseable"},
    ]

    scores = rough_scores(verdicts, answerable)

    assert scores["n"] == 4 and scores["errors"] == {"unparseable": 1}
    assert scores["all"]["correctness"] == {"0": 1, "1": 1, "2": 1}
    assert scores["all"]["faithful"] == {"true": 2, "false": 1}
    assert scores["all"]["mean_correctness"] == pytest.approx(1.0)
    assert scores["answerable"]["correctness"] == {"0": 0, "1": 1, "2": 1}
    assert scores["unanswerable"]["correctness"] == {"0": 1, "1": 0, "2": 0}
