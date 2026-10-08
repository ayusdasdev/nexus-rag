from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_tenant_id
from app.core.errors import TransientError
from app.providers.embeddings import ModelNotCached
from app.providers.reranker import Reranker, get_reranker
from app.repositories import chunk_repository
from app.repositories.vector_store import (
    VectorStore,
    VectorStoreRejected,
    get_vector_store,
)
from app.schemas.search import (
    RankedItemResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StageTimingResponse,
    TraceResponse,
)
from app.services.retrieval import Candidate, Trace, retrieve

router = APIRouter(prefix="/search", tags=["search"])


def _to_ranked(items: list[Candidate]) -> list[RankedItemResponse]:
    return [
        RankedItemResponse(
            chunk_id=c.chunk_id, score=c.score, rank=c.rank, source=c.source
        )
        for c in items
    ]


def _to_trace_response(trace: Trace) -> TraceResponse:
    return TraceResponse(
        stages=[StageTimingResponse(name=s.name, ms=s.ms) for s in trace.stages],
        dense=_to_ranked(trace.dense),
        sparse=_to_ranked(trace.sparse),
        fused=_to_ranked(trace.fused),
        rerank=_to_ranked(trace.rerank),
    )


@router.post("", response_model=SearchResponse, summary="Search the tenant's chunks")
async def search(
    request: SearchRequest,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    store: VectorStore = Depends(get_vector_store),  # noqa: B008 - FastAPI DI pattern
    reranker: Reranker = Depends(get_reranker),  # noqa: B008 - FastAPI DI pattern
) -> SearchResponse:
    """Dense + sparse search, fused by RRF and reranked. Scoped to the caller's tenant.

    document_ids, when given, restricts the search to those documents - a document the
    caller's tenant doesn't own simply matches nothing, rather than erroring. Set
    debug=true to get the retrieval trace (per-stage timing, and the ranked ids from
    each stage) in the response.
    """
    try:
        result = await retrieve(
            store=store,
            reranker=reranker,
            fetch_chunks=chunk_repository.fetch_chunks,
            tenant_id=tenant_id,
            query=request.query,
            document_ids=request.document_ids,
            limit=request.limit,
            trace=request.debug,
        )
    except TransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store is temporarily unavailable; retry the search",
        ) from exc
    except ModelNotCached as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The search service is not fully configured; try again later",
        ) from exc
    except VectorStoreRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed due to an internal error",
        ) from exc
    return SearchResponse(
        items=[
            SearchHit(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                chunk_index=item.chunk_index,
                text=item.text,
                heading_path=item.heading_path,
                page=item.page,
                score=item.score,
            )
            for item in result.items
        ],
        trace=_to_trace_response(result.trace) if result.trace is not None else None,
    )
