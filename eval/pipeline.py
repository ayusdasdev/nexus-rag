"""In-process wiring from the runner to the app's real retrieval (M8).

The runner calls app.services.retrieval.retrieve() directly - the code path behind
/v1/search - instead of going over HTTP, where the search rate limit (20, then 1/5 s)
would pace a run. Every call is scoped to the eval tenant recorded by
eval/tools/ingest_corpus.py; Qdrant is still reached only through VectorStore, which
applies the tenant filter. Reranker scores go through the disk cache.
"""

import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.retrieval import RetrieveResult
from eval.runner import Hit, RunConfig, SearchFn, SearchResult

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "eval" / "state" / "eval_tenant.json"
RERANK_CACHE = ROOT / "eval" / "state" / "rerank_cache.sqlite"

RetrieveFn = Callable[..., Awaitable[RetrieveResult]]


def build_search(
    retrieve_fn: RetrieveFn, tenant_id: UUID, doc_names: Mapping[UUID, str]
) -> SearchFn:
    async def search(question: dict[str, Any], config: RunConfig) -> SearchResult:
        result = await retrieve_fn(
            tenant_id=tenant_id,
            query=question["question"],
            limit=config.limit,
            candidates=config.candidates,
            use_dense=config.mode in ("dense", "hybrid"),
            use_sparse=config.mode in ("sparse", "hybrid"),
            use_rerank=config.rerank,
            expand=config.expand,
            trace=True,
        )
        hits = [
            Hit(
                chunk_id=str(item.chunk_id),
                document=doc_names.get(item.document_id, str(item.document_id)),
                chunk_index=item.chunk_index,
                text=item.text,
                score=item.score,
            )
            for item in result.items
        ]
        stages = {s.name: s.ms for s in result.trace.stages} if result.trace else {}
        return SearchResult(hits=hits, stages_ms=stages)

    return search


def make_search(generate: bool) -> tuple[SearchFn, Callable[[], Awaitable[None]]]:
    """The real search for the eval tenant. Models load on first use, not at import."""
    if generate:
        raise SystemExit(
            "generation runs are not wired yet (they come with eval/judge.py)"
        )
    from functools import partial

    from app.providers.reranker import get_reranker
    from app.repositories import chunk_repository
    from app.repositories.session import dispose_engine
    from app.repositories.vector_store import get_vector_store
    from app.services.retrieval import retrieve
    from eval.rerank_cache import CachingReranker

    state = json.loads(STATE.read_text())
    doc_names = {UUID(d["id"]): d["file"] for d in state["documents"]}
    retrieve_fn = partial(
        retrieve,
        store=get_vector_store(),
        reranker=CachingReranker(get_reranker(), RERANK_CACHE),
        fetch_chunks=chunk_repository.fetch_chunks,
        fetch_neighbors=chunk_repository.fetch_neighbors,
    )
    return build_search(
        retrieve_fn, UUID(state["tenant_id"]), doc_names
    ), dispose_engine
