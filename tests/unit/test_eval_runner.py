"""eval/runner.py with a fake search: overrides, hold-out guard, per-question writes,
resume, run metadata and summaries (M8)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from eval import runner
from eval.runner import Hit, RunConfig, SearchResult, parse_overrides

QUESTIONS = [
    {
        "id": "q001",
        "type": "factoid",
        "answerable": True,
        "gold_mode": "any",
        "question": "How long are readings kept?",
        "gold": [{"doc": "a.md", "span": "ninety days"}],
    },
    {
        "id": "q002",
        "type": "paraphrase",
        "answerable": True,
        "gold_mode": "any",
        "question": "Which port?",
        "gold": [{"doc": "a.md", "span": "port 443"}],
    },
    {
        "id": "q003",
        "type": "multi-chunk",
        "answerable": True,
        "gold_mode": "all",
        "question": "Both?",
        "gold": [
            {"doc": "a.md", "span": "ninety days"},
            {"doc": "b.md", "span": "port 443"},
        ],
    },
    {
        "id": "q004",
        "type": "unanswerable",
        "answerable": False,
        "gold_mode": "any",
        "question": "Warranty?",
        "gold": [],
    },
]
TEXTS = {
    "q001": ["kept for ninety days", "other"],
    "q002": ["other", "other", "over port 443"],
    "q003": ["kept for ninety days", "x", "x", "x", "x", "x", "x", "x", "x", "x"],
    "q004": ["other"],
}
META = {"dataset": "test", "split_seed": 7, "git_sha": "abc123", "git_dirty": False}


def _search(calls: list[str], fail_on: str | None = None) -> runner.SearchFn:
    async def search(question: dict[str, Any], config: RunConfig) -> SearchResult:
        calls.append(question["id"])
        if question["id"] == fail_on:
            raise RuntimeError("crash mid-run")
        hits = [
            Hit(
                chunk_id=f"c{i}",
                document="a.md",
                chunk_index=i,
                text=t,
                score=1.0 / (i + 1),
            )
            for i, t in enumerate(TEXTS[question["id"]])
        ]
        return SearchResult(hits=hits, stages_ms={"embed_query": 1.0, "rerank": 2.0})

    return search


def _run(out: Path, search: runner.SearchFn, **kw: Any) -> dict[str, Any]:
    return asyncio.run(
        runner.run_questions(
            QUESTIONS,
            ["q001", "q002", "q003", "q004"],
            RunConfig(),
            search,
            out,
            META,
            **kw,
        )
    )


# --- overrides ----------------------------------------------------------------------


def test_overrides_parse_with_defaults_matching_the_app() -> None:
    assert parse_overrides([]) == RunConfig(
        mode="hybrid", rerank=True, candidates=40, expand="none", limit=10
    )
    assert parse_overrides(
        ["mode=dense", "rerank=false", "candidates=20", "expand=neighbors", "limit=5"]
    ) == RunConfig("dense", False, 20, "neighbors", 5)


@pytest.mark.parametrize(
    "bad",
    [
        "mode=fancy",
        "rerank=maybe",
        "candidates=0",
        "candidates=500",
        "limit=0",
        "expand=parent",
        "chunk_size=200",
        "noequals",
    ],
)
def test_bad_overrides_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_overrides([bad])


# --- the hold-out guard -------------------------------------------------------------


def test_the_holdout_split_needs_the_explicit_final_flag() -> None:
    with pytest.raises(SystemExit, match="final-holdout"):
        runner.check_split_allowed("holdout", final_holdout=False)
    runner.check_split_allowed("holdout", final_holdout=True)
    runner.check_split_allowed("dev", final_holdout=False)


# --- writing, resuming, metadata ----------------------------------------------------


def test_each_question_is_written_as_soon_as_it_finishes(tmp_path: Path) -> None:
    calls: list[str] = []
    with pytest.raises(RuntimeError, match="crash"):
        _run(tmp_path, _search(calls, fail_on="q003"))

    lines = [
        json.loads(line)
        for line in (tmp_path / "results.jsonl").read_text().splitlines()
    ]
    assert [line["id"] for line in lines] == ["q001", "q002"]


def test_a_crashed_run_resumes_without_repeating_finished_questions(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError):
        _run(tmp_path, _search([], fail_on="q003"))

    calls: list[str] = []
    _run(tmp_path, _search(calls))

    assert calls == ["q003", "q004"]
    lines = [
        json.loads(line)
        for line in (tmp_path / "results.jsonl").read_text().splitlines()
    ]
    assert [line["id"] for line in lines] == ["q001", "q002", "q003", "q004"]


def test_resuming_with_a_different_config_is_refused(tmp_path: Path) -> None:
    _run(tmp_path, _search([]))

    with pytest.raises(SystemExit, match="config"):
        asyncio.run(
            runner.run_questions(
                QUESTIONS,
                ["q001"],
                RunConfig(mode="dense"),
                _search([]),
                tmp_path,
                META,
            )
        )


def test_the_run_records_config_dataset_seed_commit_and_timings(tmp_path: Path) -> None:
    _run(tmp_path, _search([]))

    meta = json.loads((tmp_path / "run.json").read_text())
    assert meta["config"] == {
        "mode": "hybrid",
        "rerank": True,
        "candidates": 40,
        "expand": "none",
        "limit": 10,
    }
    assert (meta["dataset"], meta["split_seed"], meta["git_sha"]) == (
        "test",
        7,
        "abc123",
    )
    assert meta["git_dirty"] is False and meta["runner_seed"] == 0
    assert meta["started_at"] and meta["finished_at"]
    line = json.loads((tmp_path / "results.jsonl").read_text().splitlines()[0])
    assert line["stages_ms"] == {"embed_query": 1.0, "rerank": 2.0}
    assert line["total_ms"] >= 0


# --- per-question metrics and the summary -------------------------------------------


def test_lines_carry_retrieval_metrics_and_unanswerables_carry_none(
    tmp_path: Path,
) -> None:
    _run(tmp_path, _search([]))
    lines = {
        json.loads(x)["id"]: json.loads(x)
        for x in (tmp_path / "results.jsonl").read_text().splitlines()
    }

    assert lines["q001"]["first_hit_rank"] == 1 and lines["q001"]["recall"]["1"] == 1.0
    assert lines["q002"]["first_hit_rank"] == 3 and lines["q002"]["recall"]["1"] == 0.0
    assert lines["q002"]["recall"]["3"] == 1.0
    # multi-chunk, mode all: one of two spans in the top 10
    assert lines["q003"]["recall"]["10"] == 0.5
    assert lines["q004"]["recall"] is None and lines["q004"]["first_hit_rank"] is None


def test_the_summary_reports_means_with_raw_counts_overall_and_per_type(
    tmp_path: Path,
) -> None:
    summary = _run(tmp_path, _search([]))

    overall = summary["overall"]
    assert overall["n"] == 3  # answerable questions only
    # recall@1: q001 1, q002 0, q003 0.5 (one of two spans): mean 1.5/3, fully covered 1 of 3
    assert overall["recall@1"] == {"mean": pytest.approx(0.5), "full": 1, "n": 3}
    assert overall["recall@3"] == {"mean": pytest.approx(5 / 6), "full": 2, "n": 3}
    assert overall["mrr"] == pytest.approx((1 + 1 / 3 + 1) / 3)
    assert summary["per_type"]["paraphrase"]["recall@3"]["full"] == 1
    assert summary["unanswerable_n"] == 1
    assert json.loads((tmp_path / "summary.json").read_text()) == summary
