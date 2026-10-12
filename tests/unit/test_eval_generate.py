"""The runner's --generate path with FakeLLM: one answer per question through the app's
real answer pipeline, captured event by event, with the deterministic checks (M8)."""

import asyncio
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.providers.llm import ChatMessage, FakeLLM, LLMUnavailable
from app.services.chat import REFUSAL
from app.services.retrieval import RetrievedChunk, RetrieveResult
from eval import runner
from eval.pipeline import build_search, make_answerer
from eval.runner import RunConfig

TENANT, DOC = uuid4(), uuid4()
CHUNK = "Readings are kept for ninety days at full resolution."
Q = {
    "id": "q001",
    "type": "factoid",
    "answerable": True,
    "gold_mode": "any",
    "question": "How long are readings kept?",
    "reference_answer": "90 days.",
    "gold": [{"doc": "a.md", "span": "kept for ninety days"}],
}
U = {
    "id": "q052",
    "type": "unanswerable",
    "answerable": False,
    "gold_mode": "any",
    "question": "Warranty?",
    "reference_answer": "",
    "gold": [],
}
SETTINGS = Settings(llm_provider="ollama")


def _retrieve(items: int = 1) -> Any:
    async def retrieve(**kwargs: Any) -> RetrieveResult:
        return RetrieveResult(
            items=[
                RetrievedChunk(
                    chunk_id=UUID(int=i + 1),
                    document_id=DOC,
                    chunk_index=i,
                    text=CHUNK,
                    heading_path=None,
                    page=None,
                    score=1.0,
                    rank=i + 1,
                )
                for i in range(items)
            ],
            trace=None,
        )

    return retrieve


class Failing(FakeLLM):
    def __init__(self) -> None:
        super().__init__([])

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncGenerator[str, None]:
        raise LLMUnavailable("down")
        yield ""  # pragma: no cover


def _answer(llm: FakeLLM, question: dict[str, Any], items: int = 1) -> dict[str, Any]:
    search = build_search(
        _retrieve(items), TENANT, {DOC: "a.md"}, answer_fn=make_answerer(llm, SETTINGS)
    )
    result = asyncio.run(search(question, RunConfig(limit=6)))
    assert result.answer is not None
    assert "generate" in result.stages_ms
    return result.answer


def test_an_answer_is_captured_with_kept_and_dropped_citations() -> None:
    answer = _answer(FakeLLM(["Ninety ", "days [1][9]."]), Q)

    assert answer["text"] == "Ninety days [1]."
    assert (answer["cited"], answer["dropped"], answer["refused"]) == ([1], [9], False)
    assert answer["sources"] == [CHUNK]
    assert answer["error"] is None
    assert answer["first_token_ms"] is not None and answer["generate_ms"] >= 0
    assert answer["raw_text"] == "Ninety days [1][9]."


def test_the_apps_malformed_citation_report_is_captured_and_checked(
    tmp_path: Path,
) -> None:
    answer = _answer(FakeLLM(["[M6] Ninety days [1]and"]), Q)

    assert answer["malformed"] == ["[M6]", "[1]and"]
    assert answer["text"] == "[M6] Ninety days [1] and"


def test_no_sources_is_the_refusal_with_no_llm_call() -> None:
    llm = FakeLLM(["never"])
    answer = _answer(llm, U, items=0)

    assert answer["text"] == REFUSAL and answer["refused"] is True and llm.calls == []


def test_a_provider_failure_is_recorded_as_an_error_not_an_answer() -> None:
    answer = _answer(Failing(), Q)

    assert answer["text"] is None and answer["error"] == "llm_unavailable"


def test_only_ollama_is_allowed_for_eval_generation() -> None:
    with pytest.raises(SystemExit, match="ollama"):
        make_answerer(FakeLLM([]), Settings.model_construct(llm_provider="anthropic"))


def test_result_lines_carry_the_deterministic_checks(tmp_path: Path) -> None:
    search = build_search(
        _retrieve(),
        TENANT,
        {DOC: "a.md"},
        answer_fn=make_answerer(FakeLLM(["Ninety days [1]."]), SETTINGS),
    )

    asyncio.run(
        runner.run_questions(
            [Q], ["q001"], RunConfig(limit=6), search, tmp_path, {"dataset": "t"}
        )
    )

    import json

    line = json.loads((tmp_path / "results.jsonl").read_text())
    checks = line["checks"]
    assert checks["refusal"]["outcome"] == "answered"
    assert checks["citations"] == {
        "valid": 1,
        "invalid": 0,
        "validity": 1.0,
        "cites_gold": True,
        "malformed": [],
    }
    assert checks["facts"]["share"] == 1.0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["generation"]["answered"] == 1


def test_generate_on_the_holdout_is_refused_before_anything_loads() -> None:
    with pytest.raises(SystemExit, match="final-holdout"):
        runner.main(["--tag", "x", "--split", "holdout", "--generate"])


def test_the_real_wiring_builds_an_answerer_only_when_generating() -> None:
    from eval.pipeline import answer_fn_for

    built: list[Settings] = []

    def build(settings: Settings) -> FakeLLM:
        built.append(settings)
        return FakeLLM(["x"])

    assert answer_fn_for(False, SETTINGS, build) is None and built == []
    assert answer_fn_for(True, SETTINGS, build) is not None and built == [SETTINGS]
    with pytest.raises(SystemExit, match="ollama"):
        answer_fn_for(True, Settings.model_construct(llm_provider="anthropic"), build)
    assert len(built) == 1  # refused before any provider was built


def _scored(outcome: str, near: bool, answerable: bool) -> dict[str, Any]:
    return {
        "answerable": answerable,
        "answer": {"generate_ms": 1.0, "error": None},
        "checks": {
            "refusal": {"refused": False, "outcome": outcome, "near_refusal": near},
            "citations": {"valid": 0, "invalid": 0, "cites_gold": None},
            "facts": {"share": None},
        },
    }


def test_the_summary_counts_near_refusals_apart_from_correct_and_missed_ones() -> None:
    lines = [
        _scored("correct_refusal", False, False),
        _scored("near_refusal", True, False),
        _scored("near_refusal", True, False),
        _scored("missed_refusal", False, False),
        _scored("answered", True, True),
        _scored("answered", False, True),
    ]

    summary = runner.summarise_generation(lines)

    assert (summary["correct_refusal"], summary["near_refusal"]) == (1, 2)
    assert (summary["missed_refusal"], summary["answered"]) == (1, 2)
    assert summary["answered_with_refusal_wording"] == 1


def test_the_summary_counts_answers_with_malformed_citations() -> None:
    lines = [_scored("answered", False, True) for _ in range(3)]
    lines[0]["checks"]["citations"]["malformed"] = ["[M6]", "[3]RIGHT"]
    lines[1]["checks"]["citations"]["malformed"] = []

    assert runner.summarise_generation(lines)["answers_with_malformed_citations"] == 1


def test_the_run_configs_answer_style_reaches_the_llm() -> None:
    from app.services import prompts

    llm = FakeLLM(["Ninety days [1]."])
    search = build_search(
        _retrieve(), TENANT, {DOC: "a.md"}, answer_fn=make_answerer(llm, SETTINGS)
    )

    asyncio.run(search(Q, RunConfig(limit=6, answer_style="quote_then_cite")))

    assert llm.calls[0][0].content == prompts.load_prompt("rag_system_quote")
