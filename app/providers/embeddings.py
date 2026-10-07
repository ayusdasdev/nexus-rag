import hashlib
import math
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from fastembed import TextEmbedding
from fastembed.sparse.bm25 import Bm25

from app.core.config import get_settings

DENSE_MODEL = "BAAI/bge-base-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"
_SPARSE_MODULUS = 2**31 - 1
_FAKE_DIM = 32


class ModelNotCached(RuntimeError):
    pass


@dataclass(frozen=True)
class SparseEmbedding:
    indices: list[int]
    values: list[float]


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...


class SparseEmbedder(Protocol):
    name: str

    def embed_documents(self, texts: Sequence[str]) -> list[SparseEmbedding]: ...

    def embed_queries(self, texts: Sequence[str]) -> list[SparseEmbedding]: ...


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


def _unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return list(vector)
    return [x / norm for x in vector]


class BgeEmbedder:
    """Dense BAAI/bge-base-en-v1.5 on CPU. The model loads on first use, from cache only."""

    name = "bge-base-en-v1.5"
    dim = 768

    def __init__(self, query_instruction: str = "", batch_size: int = 32) -> None:
        self._query_instruction = query_instruction
        self._batch_size = batch_size
        self._model: TextEmbedding | None = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                self._model = TextEmbedding(
                    DENSE_MODEL,
                    cache_dir=get_settings().fastembed_cache_dir,
                    local_files_only=True,
                )
            except ValueError as exc:
                raise ModelNotCached(_hint(DENSE_MODEL)) from exc
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(list(texts))

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([self._query_instruction + text for text in texts])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().embed(texts, batch_size=self._batch_size)
        return [_unit(vector.tolist()) for vector in vectors]


class Bm25Embedder:
    """Sparse BM25 via Qdrant/bm25. Documents use embed(); queries use query_embed()."""

    name = "qdrant-bm25"

    def __init__(self) -> None:
        self._model: Bm25 | None = None

    def _load(self) -> Bm25:
        if self._model is None:
            # Point at the snapshot explicitly: fastembed's own offline lookup for
            # Qdrant/bm25 expects a GCS-style layout, not the hub layout that
            # `make fetch-models` writes.
            cache_dir = get_settings().fastembed_cache_dir
            snapshot = _snapshot_dir(cache_dir, SPARSE_MODEL)
            try:
                self._model = Bm25(
                    SPARSE_MODEL,
                    cache_dir=cache_dir,
                    specific_model_path=str(snapshot),
                    local_files_only=True,
                )
            except ValueError as exc:
                raise ModelNotCached(_hint(SPARSE_MODEL)) from exc
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[SparseEmbedding]:
        return _to_sparse(self._load().embed(list(texts)))

    def embed_queries(self, texts: Sequence[str]) -> list[SparseEmbedding]:
        return _to_sparse(self._load().query_embed(list(texts)))


def _to_sparse(embeddings: Any) -> list[SparseEmbedding]:
    return [
        SparseEmbedding(indices=item.indices.tolist(), values=item.values.tolist())
        for item in embeddings
    ]


class FakeEmbedder:
    """Deterministic unit-length vectors from a text hash. No model, no network."""

    name = f"fake-{_FAKE_DIM}"
    dim = _FAKE_DIM

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [_fake_vector(text, self.dim) for text in texts]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed_documents(texts)


class FakeSparseEmbedder:
    """Deterministic sparse vectors: one index per distinct token, value = term frequency."""

    name = "fake-sparse"

    def embed_documents(self, texts: Sequence[str]) -> list[SparseEmbedding]:
        return [_fake_sparse(text) for text in texts]

    def embed_queries(self, texts: Sequence[str]) -> list[SparseEmbedding]:
        return self.embed_documents(texts)


def _fake_vector(text: str, dim: int) -> list[float]:
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return _unit([rng.uniform(-1.0, 1.0) for _ in range(dim)])


def _fake_sparse(text: str) -> SparseEmbedding:
    counts: dict[int, float] = {}
    for word in text.lower().split():
        index = (
            int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16) % _SPARSE_MODULUS
        )
        counts[index] = counts.get(index, 0.0) + 1.0
    indices = sorted(counts)
    return SparseEmbedding(indices=indices, values=[counts[i] for i in indices])


@lru_cache
def get_embedder() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedder == "fake":
        return FakeEmbedder()
    return BgeEmbedder(
        query_instruction=settings.bge_query_instruction,
        batch_size=settings.embed_batch_size,
    )


@lru_cache
def get_sparse_embedder() -> SparseEmbedder:
    if get_settings().embedder == "fake":
        return FakeSparseEmbedder()
    return Bm25Embedder()


def is_cached() -> bool:
    try:
        BgeEmbedder()._load()
        Bm25Embedder()._load()
    except ModelNotCached:
        return False
    return True


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        cache_dir = get_settings().fastembed_cache_dir
        TextEmbedding(DENSE_MODEL, cache_dir=cache_dir, local_files_only=False)
        Bm25(SPARSE_MODEL, cache_dir=cache_dir, local_files_only=False)
        print(f"fetched {DENSE_MODEL} and {SPARSE_MODEL} into {cache_dir}")
    else:
        print("usage: python -m app.providers.embeddings --fetch", file=sys.stderr)
        sys.exit(2)
