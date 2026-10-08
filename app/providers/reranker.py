import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.core.config import get_settings
from app.providers.embeddings import ModelNotCached

RERANKER_MODEL = "BAAI/bge-reranker-base"
RERANK_MAX_CANDIDATES = 50


class Reranker(Protocol):
    """Scores (query, text) pairs. Does not truncate - see rerank() for that."""

    name: str

    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


@dataclass(frozen=True)
class RerankResult:
    scores: list[float]
    candidates_scored: int
    truncated: bool
    latency_ms: float


def _hint(model_name: str) -> str:
    return (
        f"{model_name} is not in the local cache. "
        "Run `make fetch-models` to download it explicitly."
    )


def _snapshot_dir(cache_dir: str, model_name: str) -> Path:
    repo = Path(cache_dir) / f"models--{model_name.replace('/', '--')}"
    ref = repo / "refs" / "main"
    if not ref.is_file():
        raise ModelNotCached(_hint(model_name))
    snapshot = repo / "snapshots" / ref.read_text().strip()
    if not snapshot.is_dir():
        raise ModelNotCached(_hint(model_name))
    return snapshot


class CrossEncoderReranker:
    """Cross-encoder reranking via BAAI/bge-reranker-base (ONNX, fastembed).

    Each (query, text) pair is truncated at 512 tokens by the model's own tokenizer
    config (its trained max_position_embeddings) - not a parameter this class sets.
    The model loads on first use, from cache only.
    """

    name = "bge-reranker-base"

    def __init__(self, batch_size: int = 32) -> None:
        self._batch_size = batch_size
        self._model: TextCrossEncoder | None = None

    def _load(self) -> TextCrossEncoder:
        if self._model is None:
            cache_dir = get_settings().fastembed_cache_dir
            # Same offline-lookup mismatch as Bm25Embedder: point at the snapshot
            # explicitly rather than relying on fastembed's own local_files_only lookup.
            snapshot = _snapshot_dir(cache_dir, RERANKER_MODEL)
            try:
                self._model = TextCrossEncoder(
                    RERANKER_MODEL,
                    cache_dir=cache_dir,
                    specific_model_path=str(snapshot),
                    local_files_only=True,
                )
            except ValueError as exc:
                raise ModelNotCached(_hint(RERANKER_MODEL)) from exc
        return self._model

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        return list(
            self._load().rerank(query, list(texts), batch_size=self._batch_size)
        )


class FakeReranker:
    """Deterministic word-overlap (Jaccard) scoring. No model, no network."""

    name = "fake-word-overlap"

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        query_words = set(query.lower().split())
        return [_overlap(query_words, text) for text in texts]


def _overlap(query_words: set[str], text: str) -> float:
    words = set(text.lower().split())
    if not query_words or not words:
        return 0.0
    return len(query_words & words) / len(query_words | words)


@lru_cache
def get_reranker() -> Reranker:
    # Reuses the embedder setting: "fake" swaps both together for tests/dev.
    if get_settings().embedder == "fake":
        return FakeReranker()
    return CrossEncoderReranker()


def is_cached() -> bool:
    try:
        CrossEncoderReranker()._load()
    except ModelNotCached:
        return False
    return True


def rerank(reranker: Reranker, query: str, texts: Sequence[str]) -> RerankResult:
    """Truncates to RERANK_MAX_CANDIDATES, scores, and times the call."""
    truncated = len(texts) > RERANK_MAX_CANDIDATES
    capped = list(texts)[:RERANK_MAX_CANDIDATES]
    start = time.perf_counter()
    scores = reranker.score(query, capped)
    latency_ms = (time.perf_counter() - start) * 1000
    return RerankResult(
        scores=scores,
        candidates_scored=len(capped),
        truncated=truncated,
        latency_ms=latency_ms,
    )


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        cache_dir = get_settings().fastembed_cache_dir
        TextCrossEncoder(RERANKER_MODEL, cache_dir=cache_dir, local_files_only=False)
        print(f"fetched {RERANKER_MODEL} into {cache_dir}")
    else:
        print("usage: python -m app.providers.reranker --fetch", file=sys.stderr)
        sys.exit(2)
