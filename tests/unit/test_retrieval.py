import uuid
from collections.abc import Collection, Sequence
from types import SimpleNamespace

import pytest

from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder, SparseEmbedding
from app.repositories.chunk_repository import ChunkRecord
from app.repositories.vector_store import VectorHit
from app.services import retrieval
from app.services.retrieval import (
    Candidate,
    dense_candidates,
    embed_query,
    sparse_candidates,
)


class _RecordingDense:
    """Distinguishes embed_documents from embed_queries, unlike FakeEmbedder."""

    dim = 4

    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []
        self.query_calls: list[list[str]] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self.query_calls.append(list(texts))
        return [[0.0, 1.0, 0.0, 0.0] for _ in texts]


class _RecordingSparse:
    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []
        self.query_calls: list[list[str]] = []

    def embed_documents(self, texts: Sequence[str]) -> list[SparseEmbedding]:
        self.document_calls.append(list(texts))
        return [SparseEmbedding(indices=[1], values=[9.0]) for _ in texts]

    def embed_queries(self, texts: Sequence[str]) -> list[SparseEmbedding]:
        self.query_calls.append(list(texts))
        return [SparseEmbedding(indices=[2], values=[8.0]) for _ in texts]


class FakeVectorStore:
    """In-memory test double: no Qdrant, no qdrant_client import."""

    def __init__(
        self, dense_hits: list[VectorHit], sparse_hits: list[VectorHit]
    ) -> None:
        self._dense_hits = dense_hits
        self._sparse_hits = sparse_hits
        self.dense_calls: list[
            tuple[uuid.UUID, Sequence[float], int, Collection[uuid.UUID] | None]
        ] = []
        self.sparse_calls: list[
            tuple[
                uuid.UUID,
                Sequence[int],
                Sequence[float],
                int,
                Collection[uuid.UUID] | None,
            ]
        ] = []

    def search_dense(
        self,
        tenant_id: uuid.UUID,
        vector: Sequence[float],
        limit: int,
        document_ids: Collection[uuid.UUID] | None = None,
    ) -> list[VectorHit]:
        self.dense_calls.append((tenant_id, vector, limit, document_ids))
        hits = self._restrict(self._dense_hits, document_ids)
        return hits[:limit]

    def search_sparse(
        self,
        tenant_id: uuid.UUID,
        indices: Sequence[int],
        values: Sequence[float],
        limit: int,
        document_ids: Collection[uuid.UUID] | None = None,
    ) -> list[VectorHit]:
        self.sparse_calls.append((tenant_id, indices, values, limit, document_ids))
        hits = self._restrict(self._sparse_hits, document_ids)
        return hits[:limit]

    @staticmethod
    def _restrict(
        hits: list[VectorHit], document_ids: Collection[uuid.UUID] | None
    ) -> list[VectorHit]:
        if document_ids is None:
            return hits
        return [hit for hit in hits if hit.document_id in document_ids]


def _hit(n: int) -> VectorHit:
    return VectorHit(
        chunk_id=uuid.uuid4(), document_id=uuid.uuid4(), chunk_index=n, score=1.0 / n
    )


# --- embed_query --------------------------------------------------------------


def test_embed_query_uses_the_query_methods_not_the_document_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dense, sparse = _RecordingDense(), _RecordingSparse()
    monkeypatch.setattr(retrieval, "get_embedder", lambda: dense)
    monkeypatch.setattr(retrieval, "get_sparse_embedder", lambda: sparse)

    result = embed_query("battery life")

    assert dense.query_calls == [["battery life"]]
    assert dense.document_calls == []
    assert sparse.query_calls == [["battery life"]]
    assert sparse.document_calls == []
    assert result.dense == [0.0, 1.0, 0.0, 0.0]
    assert result.sparse_indices == [2]
    assert result.sparse_values == [8.0]


def test_embed_query_goes_through_get_embedder_with_the_fake_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # get_embedder/get_sparse_embedder are lru_cache'd singletons selected by
    # settings.embedder; clear them so this test's "fake" choice isn't masked by
    # (or doesn't leak into) another test's cached "bge" instance.
    from app.providers import embeddings

    monkeypatch.setattr(
        embeddings, "get_settings", lambda: SimpleNamespace(embedder="fake")
    )
    embeddings.get_embedder.cache_clear()
    embeddings.get_sparse_embedder.cache_clear()
    try:
        result = embed_query("battery life")

        assert result.dense == FakeEmbedder().embed_queries(["battery life"])[0]
        sparse = FakeSparseEmbedder().embed_queries(["battery life"])[0]
        assert result.sparse_indices == sparse.indices
        assert result.sparse_values == sparse.values
    finally:
        embeddings.get_embedder.cache_clear()
        embeddings.get_sparse_embedder.cache_clear()


# --- dense_candidates / sparse_candidates -------------------------------------


def test_dense_candidates_are_ranked_from_1_in_hit_order() -> None:
    hits = [_hit(1), _hit(2), _hit(3)]
    store = FakeVectorStore(dense_hits=hits, sparse_hits=[])
    tenant = uuid.uuid4()
    query = retrieval.QueryEmbedding(
        dense=[0.1, 0.2], sparse_indices=[], sparse_values=[]
    )

    candidates = dense_candidates(store, tenant, query, limit=3)

    assert candidates == [
        Candidate(
            chunk_id=hits[0].chunk_id, score=hits[0].score, rank=1, source="dense"
        ),
        Candidate(
            chunk_id=hits[1].chunk_id, score=hits[1].score, rank=2, source="dense"
        ),
        Candidate(
            chunk_id=hits[2].chunk_id, score=hits[2].score, rank=3, source="dense"
        ),
    ]


def test_dense_candidates_passes_the_tenant_vector_and_limit_through() -> None:
    store = FakeVectorStore(dense_hits=[], sparse_hits=[])
    tenant = uuid.uuid4()
    query = retrieval.QueryEmbedding(
        dense=[0.3, 0.4], sparse_indices=[], sparse_values=[]
    )

    dense_candidates(store, tenant, query, limit=7)

    assert store.dense_calls == [(tenant, [0.3, 0.4], 7, None)]


def test_dense_candidates_passes_document_ids_through() -> None:
    store = FakeVectorStore(dense_hits=[], sparse_hits=[])
    tenant = uuid.uuid4()
    doc_ids = {uuid.uuid4()}
    query = retrieval.QueryEmbedding(dense=[0.1], sparse_indices=[], sparse_values=[])

    dense_candidates(store, tenant, query, limit=7, document_ids=doc_ids)

    assert store.dense_calls == [(tenant, [0.1], 7, doc_ids)]


def test_sparse_candidates_are_ranked_from_1_and_sourced_as_sparse() -> None:
    hits = [_hit(1), _hit(2)]
    store = FakeVectorStore(dense_hits=[], sparse_hits=hits)
    tenant = uuid.uuid4()
    query = retrieval.QueryEmbedding(
        dense=[], sparse_indices=[5, 6], sparse_values=[1.0, 2.0]
    )

    candidates = sparse_candidates(store, tenant, query, limit=2)

    assert [c.source for c in candidates] == ["sparse", "sparse"]
    assert [c.rank for c in candidates] == [1, 2]
    assert [c.chunk_id for c in candidates] == [hits[0].chunk_id, hits[1].chunk_id]


def test_sparse_candidates_passes_the_tenant_indices_values_and_limit_through() -> None:
    store = FakeVectorStore(dense_hits=[], sparse_hits=[])
    tenant = uuid.uuid4()
    query = retrieval.QueryEmbedding(
        dense=[], sparse_indices=[5, 6], sparse_values=[1.0, 2.0]
    )

    sparse_candidates(store, tenant, query, limit=4)

    assert store.sparse_calls == [(tenant, [5, 6], [1.0, 2.0], 4, None)]


def test_sparse_candidates_passes_document_ids_through() -> None:
    store = FakeVectorStore(dense_hits=[], sparse_hits=[])
    tenant = uuid.uuid4()
    doc_ids = {uuid.uuid4()}
    query = retrieval.QueryEmbedding(dense=[], sparse_indices=[5], sparse_values=[1.0])

    sparse_candidates(store, tenant, query, limit=4, document_ids=doc_ids)

    assert store.sparse_calls == [(tenant, [5], [1.0], 4, doc_ids)]


def test_candidates_are_empty_when_the_store_has_no_hits() -> None:
    store = FakeVectorStore(dense_hits=[], sparse_hits=[])
    tenant = uuid.uuid4()
    query = retrieval.QueryEmbedding(dense=[0.0], sparse_indices=[], sparse_values=[])

    assert dense_candidates(store, tenant, query, limit=5) == []
    assert sparse_candidates(store, tenant, query, limit=5) == []


def test_fake_vector_store_satisfies_the_protocol_statically() -> None:
    # mypy --strict checks this at type-check time; this call exercises it at runtime too.
    store: retrieval.VectorSearcher = FakeVectorStore(dense_hits=[], sparse_hits=[])
    assert store.search_dense(uuid.uuid4(), [0.0], 1) == []


# --- fuse_rrf -------------------------------------------------------------------


def test_fuse_rrf_of_empty_lists_is_empty() -> None:
    assert retrieval.fuse_rrf([], []) == []


def test_fuse_rrf_ranks_a_candidate_in_both_lists_above_one_in_a_single_list() -> None:
    both = uuid.uuid4()
    dense_only = uuid.uuid4()
    dense = [
        Candidate(chunk_id=both, score=0.9, rank=1, source="dense"),
        Candidate(chunk_id=dense_only, score=0.8, rank=2, source="dense"),
    ]
    sparse = [Candidate(chunk_id=both, score=5.0, rank=1, source="sparse")]

    fused = retrieval.fuse_rrf(dense, sparse)

    assert [c.chunk_id for c in fused] == [both, dense_only]
    assert fused[0].source == "fused"
    assert fused[0].score > fused[1].score


def test_fuse_rrf_includes_a_sparse_only_candidate() -> None:
    sparse_only = uuid.uuid4()
    sparse = [Candidate(chunk_id=sparse_only, score=1.0, rank=1, source="sparse")]

    fused = retrieval.fuse_rrf([], sparse)

    assert [c.chunk_id for c in fused] == [sparse_only]


def test_fuse_rrf_scores_match_the_reciprocal_rank_formula() -> None:
    cid = uuid.uuid4()
    dense = [Candidate(chunk_id=cid, score=0.5, rank=3, source="dense")]

    fused = retrieval.fuse_rrf(dense, [])

    assert fused[0].score == pytest.approx(1.0 / (retrieval._RRF_K + 3))


def test_fuse_rrf_assigns_contiguous_ranks_from_1() -> None:
    dense = [
        Candidate(chunk_id=uuid.uuid4(), score=1.0, rank=i, source="dense")
        for i in (1, 2, 3)
    ]

    fused = retrieval.fuse_rrf(dense, [])

    assert [c.rank for c in fused] == [1, 2, 3]


def test_fuse_rrf_breaks_score_ties_by_chunk_id() -> None:
    low = uuid.UUID("00000000-0000-0000-0000-000000000001")
    high = uuid.UUID("ffffffff-0000-0000-0000-000000000000")
    # Both rank 1 in one list each: both score 1/61, so the lower id wins the tie.
    dense = [Candidate(chunk_id=high, score=0.9, rank=1, source="dense")]
    sparse = [Candidate(chunk_id=low, score=3.0, rank=1, source="sparse")]

    fused = retrieval.fuse_rrf(dense, sparse)

    assert [c.chunk_id for c in fused] == [low, high]


def test_fuse_rrf_counts_a_chunk_repeated_in_one_list_once() -> None:
    cid = uuid.uuid4()
    dense = [
        Candidate(chunk_id=cid, score=0.9, rank=1, source="dense"),
        Candidate(chunk_id=cid, score=0.8, rank=2, source="dense"),
    ]

    fused = retrieval.fuse_rrf(dense, [])

    assert fused[0].score == pytest.approx(1.0 / (retrieval._RRF_K + 1))


# --- retrieve() orchestration ---------------------------------------------------


class _TextScoredReranker:
    name = "text-scored"

    def __init__(self, scores_by_text: dict[str, float]) -> None:
        self._scores = scores_by_text

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        return [self._scores[text] for text in texts]


def _hit_id(
    chunk_id: uuid.UUID, document_id: uuid.UUID, index: int, score: float
) -> VectorHit:
    return VectorHit(
        chunk_id=chunk_id, document_id=document_id, chunk_index=index, score=score
    )


def _fetcher(records: list[ChunkRecord]) -> "retrieval.ChunkFetcher":
    by_id = {record.id: record for record in records}

    async def fetch(
        tenant_id: uuid.UUID, ids: Sequence[uuid.UUID]
    ) -> list[ChunkRecord]:
        return [by_id[i] for i in ids if i in by_id]

    return fetch


def _fixed_embed_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        retrieval,
        "embed_query",
        lambda text: retrieval.QueryEmbedding(
            dense=[0.1], sparse_indices=[1], sparse_values=[1.0]
        ),
    )


@pytest.mark.asyncio
async def test_retrieve_reranks_fused_candidates_and_returns_hydrated_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc = uuid.uuid4(), uuid.uuid4()
    c1, c2, c3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store = FakeVectorStore(
        dense_hits=[_hit_id(c1, doc, 0, 0.9), _hit_id(c2, doc, 1, 0.8)],
        sparse_hits=[_hit_id(c3, doc, 2, 5.0)],
    )
    records = [
        ChunkRecord(
            id=c1,
            document_id=doc,
            chunk_index=0,
            text="A",
            heading_path=None,
            page=None,
            token_count=1,
        ),
        ChunkRecord(
            id=c2,
            document_id=doc,
            chunk_index=1,
            text="B",
            heading_path=None,
            page=None,
            token_count=1,
        ),
        ChunkRecord(
            id=c3,
            document_id=doc,
            chunk_index=2,
            text="C",
            heading_path=None,
            page=None,
            token_count=1,
        ),
    ]
    reranker = _TextScoredReranker({"A": 0.1, "B": 0.9, "C": 0.5})

    result = await retrieval.retrieve(
        store=store,
        reranker=reranker,
        fetch_chunks=_fetcher(records),
        tenant_id=tenant,
        query="q",
        limit=10,
    )

    assert [item.chunk_id for item in result.items] == [c2, c3, c1]
    assert [item.text for item in result.items] == ["B", "C", "A"]
    assert result.trace is None


@pytest.mark.asyncio
async def test_retrieve_without_rerank_keeps_fused_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc = uuid.uuid4(), uuid.uuid4()
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    store = FakeVectorStore(
        dense_hits=[_hit_id(c1, doc, 0, 0.9), _hit_id(c2, doc, 1, 0.8)], sparse_hits=[]
    )
    records = [
        ChunkRecord(
            id=c1,
            document_id=doc,
            chunk_index=0,
            text="A",
            heading_path=None,
            page=None,
            token_count=1,
        ),
        ChunkRecord(
            id=c2,
            document_id=doc,
            chunk_index=1,
            text="B",
            heading_path=None,
            page=None,
            token_count=1,
        ),
    ]
    # This reranker would reverse the order if it ran; use_rerank=False means it never does.
    reranker = _TextScoredReranker({"A": 0.0, "B": 1.0})

    result = await retrieval.retrieve(
        store=store,
        reranker=reranker,
        fetch_chunks=_fetcher(records),
        tenant_id=tenant,
        query="q",
        limit=10,
        use_rerank=False,
    )

    assert [item.chunk_id for item in result.items] == [c1, c2]


@pytest.mark.asyncio
async def test_retrieve_skips_the_dense_search_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc = uuid.uuid4(), uuid.uuid4()
    c1 = uuid.uuid4()
    store = FakeVectorStore(
        dense_hits=[_hit_id(uuid.uuid4(), doc, 0, 0.9)],
        sparse_hits=[_hit_id(c1, doc, 1, 1.0)],
    )
    records = [
        ChunkRecord(
            id=c1,
            document_id=doc,
            chunk_index=1,
            text="only sparse",
            heading_path=None,
            page=None,
            token_count=1,
        )
    ]

    result = await retrieval.retrieve(
        store=store,
        reranker=_TextScoredReranker({"only sparse": 1.0}),
        fetch_chunks=_fetcher(records),
        tenant_id=tenant,
        query="q",
        limit=10,
        use_dense=False,
    )

    assert store.dense_calls == []
    assert [item.chunk_id for item in result.items] == [c1]


@pytest.mark.asyncio
async def test_retrieve_requires_at_least_one_of_dense_or_sparse() -> None:
    with pytest.raises(ValueError, match="use_dense or use_sparse"):
        await retrieval.retrieve(
            store=FakeVectorStore(dense_hits=[], sparse_hits=[]),
            reranker=_TextScoredReranker({}),
            fetch_chunks=_fetcher([]),
            tenant_id=uuid.uuid4(),
            query="q",
            use_dense=False,
            use_sparse=False,
        )


@pytest.mark.asyncio
async def test_retrieve_respects_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc = uuid.uuid4(), uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(3)]
    store = FakeVectorStore(
        dense_hits=[_hit_id(i, doc, n, 1.0 / (n + 1)) for n, i in enumerate(ids)],
        sparse_hits=[],
    )
    records = [
        ChunkRecord(
            id=i,
            document_id=doc,
            chunk_index=n,
            text=f"t{n}",
            heading_path=None,
            page=None,
            token_count=1,
        )
        for n, i in enumerate(ids)
    ]
    reranker = _TextScoredReranker({f"t{n}": 1.0 for n in range(3)})

    result = await retrieval.retrieve(
        store=store,
        reranker=reranker,
        fetch_chunks=_fetcher(records),
        tenant_id=tenant,
        query="q",
        limit=1,
    )

    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_retrieve_passes_document_ids_through_to_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant = uuid.uuid4()
    doc_ids = {uuid.uuid4()}
    store = FakeVectorStore(dense_hits=[], sparse_hits=[])

    await retrieval.retrieve(
        store=store,
        reranker=_TextScoredReranker({}),
        fetch_chunks=_fetcher([]),
        tenant_id=tenant,
        query="q",
        document_ids=doc_ids,
    )

    assert store.dense_calls[0][3] == doc_ids
    assert store.sparse_calls[0][4] == doc_ids


@pytest.mark.asyncio
async def test_retrieve_trace_includes_every_stage_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc = uuid.uuid4(), uuid.uuid4()
    c1 = uuid.uuid4()
    store = FakeVectorStore(dense_hits=[_hit_id(c1, doc, 0, 0.9)], sparse_hits=[])
    records = [
        ChunkRecord(
            id=c1,
            document_id=doc,
            chunk_index=0,
            text="A",
            heading_path=None,
            page=None,
            token_count=1,
        )
    ]

    result = await retrieval.retrieve(
        store=store,
        reranker=_TextScoredReranker({"A": 1.0}),
        fetch_chunks=_fetcher(records),
        tenant_id=tenant,
        query="q",
        trace=True,
    )

    assert result.trace is not None
    assert {stage.name for stage in result.trace.stages} >= {
        "embed_query",
        "dense_search",
        "fuse",
        "rerank",
    }
    assert all(stage.ms >= 0.0 for stage in result.trace.stages)
    assert [c.chunk_id for c in result.trace.dense] == [c1]
    assert [c.chunk_id for c in result.trace.fused] == [c1]
    assert [c.chunk_id for c in result.trace.rerank] == [c1]


# --- candidates and neighbor expansion ------------------------------------------


def _record(chunk_id: uuid.UUID, doc: uuid.UUID, index: int, text: str) -> ChunkRecord:
    return ChunkRecord(
        id=chunk_id,
        document_id=doc,
        chunk_index=index,
        text=text,
        heading_path=None,
        page=None,
        token_count=1,
    )


def _neighbor_fetcher(
    records: list[ChunkRecord],
    calls: list[tuple[uuid.UUID, list[tuple[uuid.UUID, int]]]],
) -> "retrieval.NeighborFetcher":
    by_key = {(r.document_id, r.chunk_index): r for r in records}

    async def fetch(
        tenant_id: uuid.UUID, keys: Sequence[tuple[uuid.UUID, int]]
    ) -> list[ChunkRecord]:
        calls.append((tenant_id, list(keys)))
        return [by_key[key] for key in keys if key in by_key]

    return fetch


@pytest.mark.asyncio
async def test_retrieve_asks_each_store_list_for_candidates_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    store = FakeVectorStore(dense_hits=[], sparse_hits=[])

    await retrieval.retrieve(
        store=store,
        reranker=_TextScoredReranker({}),
        fetch_chunks=_fetcher([]),
        tenant_id=uuid.uuid4(),
        query="q",
        candidates=17,
    )

    assert store.dense_calls[0][2] == 17
    assert store.sparse_calls[0][3] == 17


@pytest.mark.asyncio
async def test_retrieve_without_expansion_attaches_no_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    doc, c1 = uuid.uuid4(), uuid.uuid4()
    calls: list[tuple[uuid.UUID, list[tuple[uuid.UUID, int]]]] = []

    result = await retrieval.retrieve(
        store=FakeVectorStore(dense_hits=[_hit_id(c1, doc, 5, 0.9)], sparse_hits=[]),
        reranker=_TextScoredReranker({"mid": 1.0}),
        fetch_chunks=_fetcher([_record(c1, doc, 5, "mid")]),
        fetch_neighbors=_neighbor_fetcher([], calls),
        tenant_id=uuid.uuid4(),
        query="q",
    )

    assert result.items[0].neighbors == ()
    assert calls == []


@pytest.mark.asyncio
async def test_neighbor_expansion_attaches_the_chunks_either_side_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc = uuid.uuid4(), uuid.uuid4()
    hit, before, after = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    calls: list[tuple[uuid.UUID, list[tuple[uuid.UUID, int]]]] = []
    neighbors = [_record(after, doc, 6, "after"), _record(before, doc, 4, "before")]

    result = await retrieval.retrieve(
        store=FakeVectorStore(dense_hits=[_hit_id(hit, doc, 5, 0.9)], sparse_hits=[]),
        reranker=_TextScoredReranker({"mid": 1.0}),
        fetch_chunks=_fetcher([_record(hit, doc, 5, "mid")]),
        fetch_neighbors=_neighbor_fetcher(neighbors, calls),
        tenant_id=tenant,
        query="q",
        expand="neighbors",
    )

    assert [n.text for n in result.items[0].neighbors] == ["before", "after"]
    assert calls == [(tenant, [(doc, 4), (doc, 6)])]


@pytest.mark.asyncio
async def test_neighbor_expansion_skips_index_minus_one_and_missing_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc, hit = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    calls: list[tuple[uuid.UUID, list[tuple[uuid.UUID, int]]]] = []

    result = await retrieval.retrieve(
        store=FakeVectorStore(dense_hits=[_hit_id(hit, doc, 0, 0.9)], sparse_hits=[]),
        reranker=_TextScoredReranker({"first": 1.0}),
        fetch_chunks=_fetcher([_record(hit, doc, 0, "first")]),
        fetch_neighbors=_neighbor_fetcher([], calls),
        tenant_id=tenant,
        query="q",
        expand="neighbors",
    )

    # Chunk 0 has no predecessor; chunk 1 doesn't exist (single-chunk document).
    assert calls == [(tenant, [(doc, 1)])]
    assert result.items[0].neighbors == ()


@pytest.mark.asyncio
async def test_neighbor_expansion_omits_neighbors_that_are_results_themselves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc = uuid.uuid4(), uuid.uuid4()
    c4, c5 = uuid.uuid4(), uuid.uuid4()
    calls: list[tuple[uuid.UUID, list[tuple[uuid.UUID, int]]]] = []
    records = [_record(c4, doc, 4, "four"), _record(c5, doc, 5, "five")]

    result = await retrieval.retrieve(
        store=FakeVectorStore(
            dense_hits=[_hit_id(c5, doc, 5, 0.9), _hit_id(c4, doc, 4, 0.8)],
            sparse_hits=[],
        ),
        reranker=_TextScoredReranker({"four": 0.1, "five": 0.9}),
        fetch_chunks=_fetcher(records),
        fetch_neighbors=_neighbor_fetcher(records, calls),
        tenant_id=tenant,
        query="q",
        expand="neighbors",
    )

    # 4 and 5 are both returned, so neither repeats as the other's neighbor, and
    # neither is fetched again.
    assert calls == [(tenant, [(doc, 3), (doc, 6)])]
    assert [item.neighbors for item in result.items] == [(), ()]


@pytest.mark.asyncio
async def test_neighbor_expansion_is_timed_in_the_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    doc, c1 = uuid.uuid4(), uuid.uuid4()

    result = await retrieval.retrieve(
        store=FakeVectorStore(dense_hits=[_hit_id(c1, doc, 1, 0.9)], sparse_hits=[]),
        reranker=_TextScoredReranker({"mid": 1.0}),
        fetch_chunks=_fetcher([_record(c1, doc, 1, "mid")]),
        fetch_neighbors=_neighbor_fetcher([], []),
        tenant_id=uuid.uuid4(),
        query="q",
        expand="neighbors",
        trace=True,
    )

    assert result.trace is not None
    assert "expand" in {stage.name for stage in result.trace.stages}


@pytest.mark.asyncio
async def test_neighbor_expansion_without_a_neighbor_fetcher_is_an_error() -> None:
    with pytest.raises(ValueError, match="fetch_neighbors"):
        await retrieval.retrieve(
            store=FakeVectorStore(dense_hits=[], sparse_hits=[]),
            reranker=_TextScoredReranker({}),
            fetch_chunks=_fetcher([]),
            tenant_id=uuid.uuid4(),
            query="q",
            expand="neighbors",
        )


@pytest.mark.asyncio
async def test_neighbor_keys_are_ordered_numerically_by_chunk_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixed_embed_query(monkeypatch)
    tenant, doc, hit = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    calls: list[tuple[uuid.UUID, list[tuple[uuid.UUID, int]]]] = []

    await retrieval.retrieve(
        store=FakeVectorStore(dense_hits=[_hit_id(hit, doc, 10, 0.9)], sparse_hits=[]),
        reranker=_TextScoredReranker({"ten": 1.0}),
        fetch_chunks=_fetcher([_record(hit, doc, 10, "ten")]),
        fetch_neighbors=_neighbor_fetcher([], calls),
        tenant_id=tenant,
        query="q",
        expand="neighbors",
    )

    # 9 before 11 (a string sort would put "11" first).
    assert calls == [(tenant, [(doc, 9), (doc, 11)])]
