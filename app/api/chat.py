from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_tenant_id
from app.api.retrieval_errors import retrieval_errors
from app.core.config import Settings, get_settings
from app.providers.llm import LLMNotConfigured, LLMProvider
from app.providers.llm_factory import build_llm
from app.providers.reranker import Reranker, get_reranker
from app.repositories import chunk_repository
from app.repositories.vector_store import VectorStore, get_vector_store
from app.schemas.chat import (
    SSE_EXAMPLE,
    ChatRequest,
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    TokenEvent,
)
from app.services.chat import answer_events, format_sse
from app.services.retrieval import retrieve

router = APIRouter(prefix="/chat", tags=["chat"])

# No buffering anywhere between the model and the client.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def get_chat_llm(
    settings: Settings = Depends(get_settings),  # noqa: B008 - FastAPI DI pattern
) -> LLMProvider:
    """The configured LLM, or 503 before any streaming starts."""
    try:
        return build_llm(settings)
    except LLMNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The answer service is not configured; try again later",
        ) from exc


@router.post(
    "",
    summary="Answer a question from the tenant's documents (SSE stream)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-Sent Events: sources, token (repeated), citations, "
            "done; or error. Each data line is JSON. Payload schemas: "
            + ", ".join(
                m.__name__
                for m in (
                    SourcesEvent,
                    TokenEvent,
                    CitationsEvent,
                    DoneEvent,
                    ErrorEvent,
                )
            ),
            "content": {"text/event-stream": {"example": SSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid token"},
        422: {"description": "Invalid body, including any tenant_id field"},
        503: {"description": "Retrieval or the LLM is unavailable or not configured"},
    },
)
async def chat(
    request: ChatRequest,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    store: VectorStore = Depends(get_vector_store),  # noqa: B008 - FastAPI DI pattern
    reranker: Reranker = Depends(get_reranker),  # noqa: B008 - FastAPI DI pattern
    llm: LLMProvider = Depends(get_chat_llm),  # noqa: B008 - FastAPI DI pattern
    settings: Settings = Depends(get_settings),  # noqa: B008 - FastAPI DI pattern
) -> StreamingResponse:
    """Retrieve from the caller's ready documents, then stream a cited answer.

    Retrieval runs before the stream opens, so its failures are ordinary 503/500
    responses. The stream sends `sources` (numbered chunks), `token` events as the model
    writes, `citations` (only numbers that map to a sent source; others are dropped), and
    `done` with the cleaned answer. Nothing retrieved means a refusal with no LLM call. A
    provider failure mid-answer ends the stream with an `error` event. The answer is plain
    text: links in it are reported in `done.external_links`, never fetched (ADR-0007).
    """
    mode = settings.retrieval_mode
    with retrieval_errors():
        result = await retrieve(
            store=store,
            reranker=reranker,
            fetch_chunks=chunk_repository.fetch_chunks,
            fetch_neighbors=chunk_repository.fetch_neighbors,
            tenant_id=tenant_id,
            query=request.question,
            document_ids=request.document_ids,
            limit=request.limit,
            candidates=settings.candidates,
            use_dense=mode in ("dense", "hybrid"),
            use_sparse=mode in ("sparse", "hybrid"),
            use_rerank=settings.rerank,
            expand=settings.expand,
        )

    async def frames() -> AsyncIterator[str]:
        async for event in answer_events(
            request.question,
            result.items,
            llm,
            max_context_tokens=settings.max_context_tokens,
            answer_max_tokens=settings.answer_max_tokens,
        ):
            yield format_sse(event)

    return StreamingResponse(
        frames(), media_type="text/event-stream", headers=SSE_HEADERS
    )
