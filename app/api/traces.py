"""Answer feedback and query traces (M9 9.1).

Feedback attaches to the trace of the caller's own answer. A trace is readable only by an
admin of its tenant; everyone else gets the same 404 as a trace that doesn't exist.
"""

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from app.api.deps import CurrentUser, get_current_user
from app.api.rate_limit import limit_default
from app.core.request_context import SAFE_REQUEST_ID
from app.models.user import UserRole
from app.repositories import trace_repository
from app.schemas.traces import FeedbackRequest, TraceOut

router = APIRouter(tags=["traces"], dependencies=[Depends(limit_default)])


def _not_found(what: str) -> HTTPException:
    # A fresh instance per raise (a shared one grows its traceback, M6 review).
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found"
    )


@router.post(
    "/messages/{message_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Rate one of my answers (thumbs up or down)",
    responses={
        401: {"description": "Missing or invalid token"},
        404: {"description": "No answer of yours with this id"},
        422: {"description": "Invalid body or message id"},
    },
)
async def give_feedback(
    message_id: UUID,
    request: FeedbackRequest,
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> Response:
    """Attach 1 (good) or -1 (bad) to the trace of one of your own assistant messages.
    Rating again replaces the earlier value. Anyone else's message, or an unknown id, is
    404, so existence never leaks."""
    if not await trace_repository.set_feedback(
        user.tenant_id, user.id, message_id, request.value
    ):
        raise _not_found("Message")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/traces/{request_id}",
    response_model=TraceOut,
    summary="Reconstruct one answer from its request id (admins only)",
    responses={
        401: {"description": "Missing or invalid token"},
        404: {"description": "Not found, not in your tenant, or you're not an admin"},
        422: {"description": "Invalid request id"},
    },
)
async def get_trace(
    request_id: Annotated[str, Path(pattern=SAFE_REQUEST_ID)],
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> TraceOut:
    """The query trace of a chat answer or conversation turn in your tenant: question,
    rewritten query, retrieval candidates per stage (ids and scores, no document text),
    latency per stage, estimated tokens, model and answer. The id is the X-Request-ID of
    the answer's response. Admins only (ADR-0005's rule for retrieval internals)."""
    trace = None
    if user.role == UserRole.admin.value:
        trace = await trace_repository.get_by_request_id(user.tenant_id, request_id)
    if trace is None:
        raise _not_found("Trace")
    return TraceOut(
        request_id=trace.request_id,
        endpoint=cast(Literal["chat", "conversation"], trace.endpoint),
        user_id=trace.user_id,
        message_id=trace.message_id,
        query=trace.query,
        rewritten_query=trace.rewritten_query,
        stages=trace.stages,
        latency_ms=trace.latency_ms,
        prompt_tokens=trace.prompt_tokens,
        completion_tokens=trace.completion_tokens,
        model=trace.model,
        answer=trace.answer,
        error=trace.error,
        est_cost=trace.est_cost,
        feedback=cast(Literal[-1, 1] | None, trace.feedback),
        created_at=trace.created_at,
    )
