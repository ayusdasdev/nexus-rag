from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.providers import reranker
from app.providers.embeddings import ModelNotCached
from app.providers.reranker import (
    RERANK_MAX_CANDIDATES,
    CrossEncoderReranker,
    FakeReranker,
    rerank,
)


class _RecordingReranker:
    name = "recording"

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        self.calls.append((query, list(texts)))
        return self._scores[: len(texts)]


# --- FakeReranker --------------------------------------------------------------


def test_fake_reranker_gives_identical_text_a_score_of_1() -> None:
    scores = FakeReranker().score(
        "battery life calibration", ["battery life calibration"]
    )

    assert scores == [1.0]


def test_fake_reranker_gives_disjoint_text_a_score_of_0() -> None:
    scores = FakeReranker().score("battery life", ["parking passes onboarding"])

    assert scores == [0.0]


def test_fake_reranker_is_jaccard_word_overlap() -> None:
    # query={a,b}, text={a,c}: intersection 1, union 3 -> 1/3
    scores = FakeReranker().score("a b", ["a c"])

    assert scores == pytest.approx([1 / 3])


def test_fake_reranker_returns_one_score_per_text_in_order() -> None:
    scores = FakeReranker().score("a b c", ["a", "a b", "x y z"])

    assert len(scores) == 3
    assert scores[0] < scores[1]
    assert scores[2] == 0.0


def test_fake_reranker_is_deterministic() -> None:
    first = FakeReranker().score("battery", ["battery life"])
    second = FakeReranker().score("battery", ["battery life"])

    assert first == second


# --- rerank(): truncation + latency wrapper ------------------------------------


def test_rerank_truncates_to_rerank_max_candidates_before_scoring() -> None:
    texts = [f"text {i}" for i in range(RERANK_MAX_CANDIDATES + 10)]
    recorder = _RecordingReranker(scores=[0.0] * len(texts))

    result = rerank(recorder, "q", texts)

    assert len(recorder.calls[0][1]) == RERANK_MAX_CANDIDATES
    assert recorder.calls[0][1] == texts[:RERANK_MAX_CANDIDATES]
    assert result.truncated is True
    assert result.candidates_scored == RERANK_MAX_CANDIDATES


def test_rerank_does_not_truncate_when_within_the_limit() -> None:
    texts = ["a", "b", "c"]
    recorder = _RecordingReranker(scores=[0.1, 0.2, 0.3])

    result = rerank(recorder, "q", texts)

    assert recorder.calls[0][1] == texts
    assert result.truncated is False
    assert result.candidates_scored == 3
    assert result.scores == [0.1, 0.2, 0.3]


def test_rerank_reports_a_non_negative_latency() -> None:
    result = rerank(FakeReranker(), "q", ["a", "b"])

    assert isinstance(result.latency_ms, float)
    assert result.latency_ms >= 0.0


def test_rerank_passes_the_query_through_unchanged() -> None:
    recorder = _RecordingReranker(scores=[0.0])

    rerank(recorder, "exact query text", ["a"])

    assert recorder.calls[0][0] == "exact query text"


# --- CrossEncoderReranker: offline, cache-miss path ----------------------------


def test_cross_encoder_raises_clear_error_when_cache_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        reranker,
        "get_settings",
        lambda: SimpleNamespace(fastembed_cache_dir=str(tmp_path)),
    )

    with pytest.raises(ModelNotCached, match="make fetch-models"):
        CrossEncoderReranker().score("q", ["a"])
