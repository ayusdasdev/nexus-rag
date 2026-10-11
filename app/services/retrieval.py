import asyncio
import time
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol
from uuid import UUID

from app.core.config import Expand
from app.providers.embeddings import get_embedder, get_sparse_embedder
from app.providers.reranker import RERANK_MAX_CANDIDATES, Reranker, rerank
from app.repositories.chunk_repository import ChunkRecord
from app.repositories.vector_store import VectorHit
from app.services.fusion import RRF_K, rrf_from_ranks

DEFAULT_CANDIDATES = 40
_RRF_K = RRF_K

Source = Literal["dense", "sparse", "fused", "rerank"]


@dataclass(frozen=True)
class QueryEmbedding:
    dense: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


@dataclass(frozen=True)
class Candidate:
    chunk_id: UUID
    score: float
    rank: int
    source: Source


@dataclass(frozen=True)
class StageTiming:
    name: str
    ms: float


@dataclass(frozen=True)
class Trace:
    stages: list[StageTiming]
    dense: list[Candidate]
    sparse: list[Candidate]
    fused: list[Candidate]
    rerank: list[Candidate]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    text: str
    heading_path: str | None
    page: int | None
    score: float
    rank: int
    # Chunks at chunk_index -1/+1 in the same document, when expand="neighbors".
    neighbors: tuple[ChunkRecord, ...] = ()


def expanded_text(item: RetrievedChunk) -> str:
    """The hit with its attached neighbors around it, in chunk_index order: the text an
    answer is built from. Without neighbors, the hit's own text."""
    before = [n.text for n in item.neighbors if n.chunk_index < item.chunk_index]
    after = [n.text for n in item.neighbors if n.chunk_index > item.chunk_index]
    return "\n\n".join([*before, item.text, *after])


@dataclass(frozen=True)
class RetrieveResult:
    items: list[RetrievedChunk]
    trace: Trace | None


class VectorSearcher(Protocol):
    """What retrieval needs from VectorStore. Never touches qdrant_client directly."""

    def search_dense(
        self,
        tenant_id: UUID,
        vector: Sequence[float],
        limit: int,
        document_ids: Collection[UUID] | None = None,
    ) -> list[VectorHit]: ...

    def search_sparse(
        self,
        tenant_id: UUID,
        indices: Sequence[int],
        values: Sequence[float],
        limit: int,
        document_ids: Collection[UUID] | None = None,
    ) -> list[VectorHit]: ...


# What retrieve() needs from chunk_repository.fetch_chunks: an id lookup scoped to the
# tenant. Injectable so retrieve() is unit-testable without Postgres.
ChunkFetcher = Callable[[UUID, Sequence[UUID]], Awaitable[list[ChunkRecord]]]
# What expansion needs from chunk_repository.fetch_neighbors: (document_id, chunk_index)
# lookups, also scoped to the tenant.
NeighborFetcher = Callable[
    [UUID, Sequence[tuple[UUID, int]]], Awaitable[list[ChunkRecord]]
]


def embed_query(text: str) -> QueryEmbedding:
    dense = get_embedder().embed_queries([text])[0]
    sparse = get_sparse_embedder().embed_queries([text])[0]
    return QueryEmbedding(
        dense=dense, sparse_indices=sparse.indices, sparse_values=sparse.values
    )


def dense_candidates(
    store: VectorSearcher,
    tenant_id: UUID,
    query: QueryEmbedding,
    limit: int,
    document_ids: Collection[UUID] | None = None,
) -> list[Candidate]:
    hits = store.search_dense(tenant_id, query.dense, limit, document_ids)
    return [_to_candidate(hit, rank, "dense") for rank, hit in enumerate(hits, start=1)]


def sparse_candidates(
    store: VectorSearcher,
    tenant_id: UUID,
    query: QueryEmbedding,
    limit: int,
    document_ids: Collection[UUID] | None = None,
) -> list[Candidate]:
    hits = store.search_sparse(
        tenant_id, query.sparse_indices, query.sparse_values, limit, document_ids
    )
    return [
        _to_candidate(hit, rank, "sparse") for rank, hit in enumerate(hits, start=1)
    ]


def _to_candidate(hit: VectorHit, rank: int, source: Source) -> Candidate:
    return Candidate(chunk_id=hit.chunk_id, score=hit.score, rank=rank, source=source)


def fuse_rrf(
    dense: Sequence[Candidate], sparse: Sequence[Candidate]
) -> list[Candidate]:
    """Reciprocal Rank Fusion of the two candidate lists, using each candidate's rank."""
    ordered = rrf_from_ranks(
        [[(c.chunk_id, c.rank) for c in dense], [(c.chunk_id, c.rank) for c in sparse]],
        _RRF_K,
    )
    return [
        Candidate(chunk_id=chunk_id, score=score, rank=rank, source="fused")
        for rank, (chunk_id, score) in enumerate(ordered, start=1)
    ]


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


async def retrieve(
    *,
    store: VectorSearcher,
    reranker: Reranker,
    fetch_chunks: ChunkFetcher,
    tenant_id: UUID,
    query: str,
    fetch_neighbors: NeighborFetcher | None = None,
    document_ids: Collection[UUID] | None = None,
    limit: int = 10,
    candidates: int = DEFAULT_CANDIDATES,
    use_dense: bool = True,
    use_sparse: bool = True,
    use_rerank: bool = True,
    expand: Expand = "none",
    trace: bool = False,
) -> RetrieveResult:
    """Embed -> dense/sparse search -> RRF fuse -> optional rerank -> hydrate from Postgres
    -> optional neighbor expansion.

    use_dense/use_sparse/use_rerank let a caller skip a stage; candidates is how many
    results each search returns. document_ids, when given, restricts the vector search
    (not just a post-filter) to those documents. Every search and fetch is
    tenant-scoped; this never trusts anything but tenant_id for that.
    """
    if not use_dense and not use_sparse:
        raise ValueError("at least one of use_dense or use_sparse must be true")
    if expand == "neighbors" and fetch_neighbors is None:
        raise ValueError("expand='neighbors' needs fetch_neighbors")

    stages: list[StageTiming] = []

    start = time.perf_counter()
    query_embedding = await asyncio.to_thread(embed_query, query)
    stages.append(StageTiming("embed_query", _elapsed_ms(start)))

    dense: list[Candidate] = []
    if use_dense:
        start = time.perf_counter()
        dense = await asyncio.to_thread(
            dense_candidates,
            store,
            tenant_id,
            query_embedding,
            candidates,
            document_ids,
        )
        stages.append(StageTiming("dense_search", _elapsed_ms(start)))

    sparse: list[Candidate] = []
    if use_sparse:
        start = time.perf_counter()
        sparse = await asyncio.to_thread(
            sparse_candidates,
            store,
            tenant_id,
            query_embedding,
            candidates,
            document_ids,
        )
        stages.append(StageTiming("sparse_search", _elapsed_ms(start)))

    start = time.perf_counter()
    fused = fuse_rrf(dense, sparse)
    stages.append(StageTiming("fuse", _elapsed_ms(start)))

    # Hydrate the whole fused list (at most 2 x candidates ids) before cutting it, so a
    # chunk fetch_chunks drops (another tenant's, or a document that isn't ready) never
    # takes a slot in limit or in the rerank window.
    start = time.perf_counter()
    records = await fetch_chunks(tenant_id, [c.chunk_id for c in fused])
    stages.append(StageTiming("fetch_chunks", _elapsed_ms(start)))
    by_id = {record.id: record for record in records}
    available = [c for c in fused if c.chunk_id in by_id]

    rerank_items: list[Candidate] = []
    if use_rerank and available:
        ordered = available[:RERANK_MAX_CANDIDATES]
        texts = [by_id[c.chunk_id].text for c in ordered]

        start = time.perf_counter()
        scored = await asyncio.to_thread(rerank, reranker, query, texts)
        stages.append(StageTiming("rerank", _elapsed_ms(start)))

        pairs = sorted(
            zip(ordered, scored.scores, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        rerank_items = [
            Candidate(
                chunk_id=candidate.chunk_id, score=score, rank=rank, source="rerank"
            )
            for rank, (candidate, score) in enumerate(pairs, start=1)
        ]
        final_ranking = rerank_items[:limit]
    else:
        final_ranking = available[:limit]

    items = [
        RetrievedChunk(
            chunk_id=candidate.chunk_id,
            document_id=by_id[candidate.chunk_id].document_id,
            chunk_index=by_id[candidate.chunk_id].chunk_index,
            text=by_id[candidate.chunk_id].text,
            heading_path=by_id[candidate.chunk_id].heading_path,
            page=by_id[candidate.chunk_id].page,
            score=candidate.score,
            rank=candidate.rank,
        )
        for candidate in final_ranking
        if candidate.chunk_id in by_id
    ]

    if expand == "neighbors" and fetch_neighbors is not None:
        start = time.perf_counter()
        items = await _attach_neighbors(items, tenant_id, fetch_neighbors)
        stages.append(StageTiming("expand", _elapsed_ms(start)))

    result_trace = (
        Trace(
            stages=stages, dense=dense, sparse=sparse, fused=fused, rerank=rerank_items
        )
        if trace
        else None
    )
    return RetrieveResult(items=items, trace=result_trace)


async def _attach_neighbors(
    items: list[RetrievedChunk], tenant_id: UUID, fetch_neighbors: NeighborFetcher
) -> list[RetrievedChunk]:
    """Attach chunk_index -1/+1 of each item, skipping chunks already returned as items."""
    returned = {(item.document_id, item.chunk_index) for item in items}
    wanted: list[tuple[UUID, int]] = []
    for item in items:
        for index in (item.chunk_index - 1, item.chunk_index + 1):
            key = (item.document_id, index)
            if index >= 0 and key not in returned and key not in wanted:
                wanted.append(key)
    if not wanted:
        return items
    found = {
        (record.document_id, record.chunk_index): record
        for record in await fetch_neighbors(
            tenant_id, sorted(wanted, key=lambda key: (str(key[0]), key[1]))
        )
    }
    return [
        replace(
            item,
            neighbors=tuple(
                found[(item.document_id, index)]
                for index in (item.chunk_index - 1, item.chunk_index + 1)
                if (item.document_id, index) in found
            ),
        )
        for item in items
    ]
