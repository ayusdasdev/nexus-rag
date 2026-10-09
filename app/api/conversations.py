import asyncio
from functools import partial
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.chat import (
    get_answer_slots,
    get_chat_llm,
    retrieve_for_answer,
    sse_response,
)
from app.api.deps import CurrentUser, get_current_user, get_tenant_id
from app.api.pagination import AFTER, page, time_cursor_key, time_key
from app.core.config import Settings, get_settings
from app.models.conversation import MessageRole
from app.providers.llm import LLMProvider
from app.providers.reranker import Reranker, get_reranker
from app.repositories import conversation_repository
from app.repositories.conversation_repository import ConversationRecord, MessageRecord
from app.repositories.vector_store import VectorStore, get_vector_store
from app.schemas.chat import SSE_EXAMPLE
from app.schemas.conversations import (
    ConversationCreate,
    ConversationDetail,
    ConversationList,
    ConversationMessageRequest,
    ConversationOut,
    MessageOut,
)
from app.services.chat import answer_events
from app.services.conversations import history_turns, persisted_events
from app.services.rewriting import rewrite_query, trim_history

router = APIRouter(prefix="/conversations", tags=["conversations"])

# History is trimmed by tokens; this only bounds how many rows are read to do that.
HISTORY_LOAD_MESSAGES = 50


def _limit_reached(what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=f"{what} limit reached"
    )


def not_found() -> HTTPException:
    """One response for "not yours" and "doesn't exist", so existence never leaks
    (ADR-0009). A fresh instance per raise: a shared one grows its traceback forever."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
    )


def _out(record: ConversationRecord) -> ConversationOut:
    return ConversationOut(
        id=record.id, title=record.title, created_at=record.created_at
    )


def _message_out(record: MessageRecord) -> MessageOut:
    return MessageOut(
        id=record.id,
        role=cast(Literal["user", "assistant"], record.role),
        content=record.content,
        sources=record.sources,
        rewritten_query=record.rewritten_query,
        model=record.model,
        truncated=record.truncated,
        created_at=record.created_at,
    )


@router.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation",
)
async def create_conversation(
    body: ConversationCreate,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
    settings: Settings = Depends(get_settings),  # noqa: B008 - FastAPI DI pattern
) -> ConversationOut:
    """Create a conversation owned by the caller. Only they will ever see it. 409 past
    MAX_CONVERSATIONS_PER_USER."""
    if (
        await conversation_repository.count_conversations(tenant_id, user.id)
        >= settings.max_conversations_per_user
    ):
        raise _limit_reached("Conversation")
    record = await conversation_repository.create_conversation(
        tenant_id, user.id, body.title
    )
    return _out(record)


@router.get("", response_model=ConversationList, summary="List my conversations")
async def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    after: str | None = AFTER,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> ConversationList:
    """The caller's own conversations, newest first, one cursor page at a time. Other
    users' never appear, and a cursor issued to someone else is rejected."""
    scope = f"conversations:{tenant_id}:{user.id}"
    rows, total = await conversation_repository.list_conversations(
        tenant_id, user.id, limit=limit + 1, after=time_key(after, scope)
    )
    records, next_cursor = page(
        rows, limit, scope, lambda r: time_cursor_key(r.created_at, r.id)
    )
    return ConversationList(
        items=[_out(r) for r in records],
        total=total,
        limit=limit,
        next_cursor=next_cursor,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Get one of my conversations with its messages",
    responses={404: {"description": "Not found, or not yours (indistinguishable)"}},
)
async def get_conversation(
    conversation_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    after: str | None = AFTER,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> ConversationDetail:
    """The conversation and one cursor page of its messages, oldest first. 404 unless the
    caller owns it (checked before the cursor, so a non-owner always gets the 404)."""
    record = await conversation_repository.get_conversation(
        tenant_id, user.id, conversation_id
    )
    if record is None:
        raise not_found()
    scope = f"messages:{tenant_id}:{user.id}:{conversation_id}"
    rows = await conversation_repository.list_messages(
        tenant_id,
        user.id,
        conversation_id,
        limit=limit + 1,
        after=time_key(after, scope),
    )
    total = await conversation_repository.count_messages(
        tenant_id, user.id, conversation_id
    )
    if rows is None or total is None:
        raise not_found()
    messages, next_cursor = page(
        rows, limit, scope, lambda m: time_cursor_key(m.created_at, m.id)
    )
    return ConversationDetail(
        **_out(record).model_dump(),
        messages=[_message_out(m) for m in messages],
        messages_total=total,
        next_cursor=next_cursor,
    )


@router.post(
    "/{conversation_id}/messages",
    summary="Ask a follow-up in one of my conversations (SSE stream)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Same events as POST /v1/chat; `sources` also carries "
            "`rewritten_query`, the query retrieval actually used.",
            "content": {"text/event-stream": {"example": SSE_EXAMPLE}},
        },
        404: {"description": "Not found, or not yours (indistinguishable)"},
    },
)
async def post_message(
    conversation_id: UUID,
    request: ConversationMessageRequest,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
    store: VectorStore = Depends(get_vector_store),  # noqa: B008 - FastAPI DI pattern
    reranker: Reranker = Depends(get_reranker),  # noqa: B008 - FastAPI DI pattern
    llm: LLMProvider = Depends(get_chat_llm),  # noqa: B008 - FastAPI DI pattern
    slots: asyncio.Semaphore = Depends(get_answer_slots),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008 - FastAPI DI pattern
) -> StreamingResponse:
    """Add a user turn and stream the answer (guide 6.3, ADR-0009).

    404 unless the caller owns the conversation. The user message is saved before anything
    else can fail. Earlier turns are trimmed to HISTORY_MAX_TOKENS; on any turn after the
    first, the question is rewritten for retrieval (REWRITE_MODE, default rule). The
    assistant message is saved when the stream ends: the cleaned answer, or the partial
    text with truncated=true after an error or a disconnect.
    """
    count = await conversation_repository.count_messages(
        tenant_id, user.id, conversation_id
    )
    earlier = await conversation_repository.recent_history(
        tenant_id, user.id, conversation_id, limit=HISTORY_LOAD_MESSAGES
    )
    if count is None or earlier is None:
        raise not_found()
    # A turn adds two messages; refuse before writing anything.
    if count + 2 > settings.conversation_max_messages:
        raise _limit_reached("Conversation message")
    history = trim_history(history_turns(earlier), settings.history_max_tokens)
    saved = await conversation_repository.add_message(
        tenant_id,
        user.id,
        conversation_id,
        role=MessageRole.user,
        content=request.question,
    )
    if saved is None:
        # Deleted between the ownership check and the save: nothing to answer into.
        raise not_found()

    query = await rewrite_query(
        history,
        request.question,
        mode=settings.rewrite_mode,
        llm=llm,
        slots=slots,
        timeout_seconds=settings.llm_answer_deadline_seconds,
    )
    items = await retrieve_for_answer(
        store,
        reranker,
        settings,
        tenant_id=tenant_id,
        query=query,
        document_ids=request.document_ids,
        limit=request.limit,
    )
    events = answer_events(
        request.question,
        items,
        llm,
        max_context_tokens=settings.max_context_tokens,
        answer_max_tokens=settings.answer_max_tokens,
        deadline_seconds=settings.llm_answer_deadline_seconds,
        slots=slots,
        history=history,
        rewritten_query=query,
    )
    save = partial(
        conversation_repository.add_message,
        tenant_id,
        user.id,
        conversation_id,
        role=MessageRole.assistant,
    )
    model = str(getattr(llm, "model", llm.name))
    return sse_response(
        persisted_events(events, save=save, model=model, rewritten_query=query)
    )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one of my conversations and its messages",
    responses={404: {"description": "Not found, or not yours (indistinguishable)"}},
)
async def delete_conversation(
    conversation_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> Response:
    """Delete the caller's conversation; its messages go with it. 404 unless they own it."""
    deleted = await conversation_repository.delete_conversation(
        tenant_id, user.id, conversation_id
    )
    if not deleted:
        raise not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
