"""The rerank score cache: no (model, query, text) pair is scored twice, across runs."""

from collections.abc import Sequence
from pathlib import Path

from eval.rerank_cache import CachingReranker


class Counting:
    name = "fake-reranker"

    def __init__(self) -> None:
        self.pairs: list[tuple[str, str]] = []

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        self.pairs += [(query, t) for t in texts]
        return [float(len(t)) for t in texts]


def test_only_new_pairs_reach_the_model_and_the_cache_survives_restarts(
    tmp_path: Path,
) -> None:
    inner = Counting()
    cache = CachingReranker(inner, tmp_path / "rerank.sqlite")

    assert cache.score("q", ["aa", "bbb"]) == [2.0, 3.0]
    assert cache.score("q", ["bbb", "c"]) == [3.0, 1.0]
    again = CachingReranker(inner, tmp_path / "rerank.sqlite")
    assert again.score("q", ["aa", "c"]) == [2.0, 1.0]
    assert again.score("other", ["aa"]) == [2.0]

    assert inner.pairs == [("q", "aa"), ("q", "bbb"), ("q", "c"), ("other", "aa")]
    assert again.name == "fake-reranker"
