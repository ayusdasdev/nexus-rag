import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.providers import embeddings
from app.providers.embeddings import (
    BgeEmbedder,
    Bm25Embedder,
    FakeEmbedder,
    FakeSparseEmbedder,
    ModelNotCached,
    get_embedder,
    get_sparse_embedder,
)


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


class _Vec:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def tolist(self) -> list[float]:
        return list(self._values)


class _StubDense:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def embed(self, texts: Any, batch_size: int = 256, **_: Any) -> list[_Vec]:
        self.calls.append((list(texts), batch_size))
        return [_Vec([3.0, 4.0] + [0.0] * 766) for _ in texts]


class _StubSparse:
    def __init__(self) -> None:
        self.embed_calls: list[list[str]] = []
        self.query_calls: list[list[str]] = []

    def _emb(self, texts: Any) -> list[Any]:
        return [
            SimpleNamespace(indices=_Vec([1, 2]), values=_Vec([1.0, 2.0]))
            for _ in texts
        ]

    def embed(self, texts: Any, **_: Any) -> list[Any]:
        self.embed_calls.append(list(texts))
        return self._emb(texts)

    def query_embed(self, texts: Any, **_: Any) -> list[Any]:
        self.query_calls.append(list(texts))
        return self._emb(texts)


# --- fakes -----------------------------------------------------------------


def test_fake_embedder_identity_and_shape() -> None:
    assert FakeEmbedder.name == "fake-32"
    assert FakeEmbedder.dim == 32


def test_fake_embedder_is_deterministic_across_instances() -> None:
    first = FakeEmbedder().embed_documents(["hello world"])[0]
    second = FakeEmbedder().embed_documents(["hello world"])[0]

    assert first == second
    assert len(first) == 32


def test_fake_embedder_vectors_are_unit_length() -> None:
    for vector in FakeEmbedder().embed_documents(["alpha", "beta gamma", ""]):
        assert math.isclose(_norm(vector), 1.0, rel_tol=1e-9)


def test_fake_embedder_differs_for_different_text() -> None:
    a, b = FakeEmbedder().embed_documents(["alpha", "beta"])

    assert a != b


def test_fake_embedder_queries_match_documents_for_the_fake() -> None:
    assert FakeEmbedder().embed_queries(["q"]) == FakeEmbedder().embed_documents(["q"])


def test_fake_sparse_value_is_term_frequency() -> None:
    embedding = FakeSparseEmbedder().embed_documents(["a a b"])[0]

    assert len(embedding.indices) == 2
    assert sorted(embedding.values) == [1.0, 2.0]


def test_fake_sparse_is_deterministic() -> None:
    first = FakeSparseEmbedder().embed_documents(["hello world"])[0]
    second = FakeSparseEmbedder().embed_documents(["hello world"])[0]

    assert first == second


def test_fake_sparse_distinct_words_get_distinct_indices() -> None:
    embedding = FakeSparseEmbedder().embed_documents(["alpha beta gamma"])[0]

    assert len(set(embedding.indices)) == 3


# --- BGE (stubbed model, no files needed) ----------------------------------


def _bge_with_stub(
    monkeypatch: pytest.MonkeyPatch, **kwargs: Any
) -> tuple[BgeEmbedder, _StubDense]:
    stub = _StubDense()
    provider = BgeEmbedder(**kwargs)
    monkeypatch.setattr(provider, "_load", lambda: stub)
    return provider, stub


def test_bge_declares_its_model_name_and_dimension() -> None:
    assert BgeEmbedder.name == "bge-base-en-v1.5"
    assert BgeEmbedder.dim == 768


def test_bge_output_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, _ = _bge_with_stub(monkeypatch)

    vector = provider.embed_documents(["x"])[0]

    assert math.isclose(_norm(vector), 1.0, rel_tol=1e-9)
    assert math.isclose(vector[0], 0.6) and math.isclose(vector[1], 0.8)


def test_bge_passes_configured_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, stub = _bge_with_stub(monkeypatch, batch_size=7)

    provider.embed_documents(["a", "b"])

    assert stub.calls == [(["a", "b"], 7)]


def test_bge_documents_are_not_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, stub = _bge_with_stub(
        monkeypatch, query_instruction="Represent this sentence: "
    )

    provider.embed_documents(["battery life"])

    assert stub.calls[0][0] == ["battery life"]


def test_bge_queries_get_the_instruction_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, stub = _bge_with_stub(
        monkeypatch, query_instruction="Represent this sentence: "
    )

    provider.embed_queries(["battery life"])

    assert stub.calls[0][0] == ["Represent this sentence: battery life"]


def test_bge_queries_are_unprefixed_when_no_instruction_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, stub = _bge_with_stub(monkeypatch)

    provider.embed_queries(["battery life"])

    assert stub.calls[0][0] == ["battery life"]


def test_bge_raises_clear_error_when_cache_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(fastembed_cache_dir=str(tmp_path)),
    )

    with pytest.raises(ModelNotCached, match="make fetch-models"):
        BgeEmbedder().embed_documents(["x"])


def test_bm25_raises_clear_error_when_cache_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(fastembed_cache_dir=str(tmp_path)),
    )

    with pytest.raises(ModelNotCached, match="make fetch-models"):
        Bm25Embedder().embed_documents(["x"])


def test_bm25_documents_use_embed_and_queries_use_query_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubSparse()
    provider = Bm25Embedder()
    monkeypatch.setattr(provider, "_load", lambda: stub)

    provider.embed_documents(["doc text"])
    provider.embed_queries(["query text"])

    assert stub.embed_calls == [["doc text"]]
    assert stub.query_calls == [["query text"]]


# --- selection and import-time behaviour -----------------------------------


def test_get_embedder_selects_fake_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: SimpleNamespace(embedder="fake")
    )

    assert isinstance(get_embedder.__wrapped__(), FakeEmbedder)


def test_get_embedder_selects_bge_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(
            embedder="bge", bge_query_instruction="", embed_batch_size=16
        ),
    )

    provider = get_embedder.__wrapped__()

    assert isinstance(provider, BgeEmbedder)
    assert provider._batch_size == 16


def test_get_sparse_embedder_selects_fake_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: SimpleNamespace(embedder="fake")
    )

    assert isinstance(get_sparse_embedder.__wrapped__(), FakeSparseEmbedder)


def test_building_providers_loads_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("model loaded eagerly")

    monkeypatch.setattr(embeddings, "TextEmbedding", boom)
    monkeypatch.setattr(embeddings, "Bm25", boom)

    provider = BgeEmbedder()
    sparse = Bm25Embedder()

    assert provider._model is None
    assert sparse._model is None
