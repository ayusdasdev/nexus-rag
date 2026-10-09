from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, get_current_user, get_tenant_id
from app.api.rate_limit import limit_search
from app.api.retrieval_errors import retrieval_errors
from app.core.config import Settings, get_settings
from app.models.user import UserRole
from app.providers.reranker import Reranker, get_reranker
from app.repositories import chunk_repository
from app.repositories.vector_store import VectorStore, get_vector_store
from app.schemas.search import (
    NeighborChunk,
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


@router.post(
    "",
    response_model=SearchResponse,
    dependencies=[Depends(limit_search)],
    summary="Search the tenant's chunks",
)
async def search(
    request: SearchRequest,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    current_user: CurrentUser = Depends(get_current_user),  # noqa: B008
    store: VectorStore = Depends(get_vector_store),  # noqa: B008 - FastAPI DI pattern
    reranker: Reranker = Depends(get_reranker),  # noqa: B008 - FastAPI DI pattern
    settings: Settings = Depends(get_settings),  # noqa: B008 - FastAPI DI pattern
) -> SearchResponse:
    """Dense + sparse search, fused by RRF and reranked. Scoped to the caller's tenant.

    mode (dense|sparse|hybrid), rerank, candidates and expand (none|neighbors) each
    default to the matching setting when omitted. document_ids, when given, restricts
    the search to those documents - a document the caller's tenant doesn't own simply
    matches nothing, rather than erroring. Only chunks of ready documents are returned.
    debug=true (admins only; 403 otherwise) adds the retrieval trace: per-stage timing
    and the ranked ids from each stage.
    """
    if request.debug and current_user.role != UserRole.admin.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="debug=true is limited to admins",
        )
    mode = request.mode if request.mode is not None else settings.retrieval_mode
    with retrieval_errors():
        result = await retrieve(
            store=store,
            reranker=reranker,
            fetch_chunks=chunk_repository.fetch_chunks,
            fetch_neighbors=chunk_repository.fetch_neighbors,
            tenant_id=tenant_id,
            query=request.query,
            document_ids=request.document_ids,
            limit=request.limit,
            candidates=(
                request.candidates
                if request.candidates is not None
                else settings.candidates
            ),
            use_dense=mode in ("dense", "hybrid"),
            use_sparse=mode in ("sparse", "hybrid"),
            use_rerank=request.rerank
            if request.rerank is not None
            else settings.rerank,
            expand=request.expand if request.expand is not None else settings.expand,
            trace=request.debug,
        )
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
                neighbors=[
                    NeighborChunk(
                        chunk_id=neighbor.id,
                        chunk_index=neighbor.chunk_index,
                        text=neighbor.text,
                    )
                    for neighbor in item.neighbors
                ],
            )
            for item in result.items
        ],
        trace=_to_trace_response(result.trace) if result.trace is not None else None,
    )
