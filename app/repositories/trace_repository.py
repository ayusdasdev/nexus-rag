"""Query traces (M9 9.1): one row per chat or conversation answer.

Tenant data. Reads are scoped by tenant; feedback only by the trace's own user. Writing a
trace also deletes that tenant's traces older than the retention period; purge_expired does
the same for every tenant (for a periodic job).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult

from app.models.trace import QueryTrace
from app.repositories.session import session_scope


@dataclass(frozen=True)
class TraceRecord:
    id: UUID
    user_id: UUID
    request_id: str
    endpoint: str
    message_id: UUID | None
    query: str
    rewritten_query: str | None
    stages: dict[str, Any]
    latency_ms: dict[str, float]
    prompt_tokens: int | None
    completion_tokens: int | None
    model: str | None
    answer: str | None
    error: str | None
    est_cost: Decimal | None
    feedback: int | None
    created_at: datetime


def _record(row: QueryTrace) -> TraceRecord:
    return TraceRecord(
        id=row.id,
        user_id=row.user_id,
        request_id=row.request_id,
        endpoint=row.endpoint,
        message_id=row.message_id,
        query=row.query,
        rewritten_query=row.rewritten_query,
        stages=row.stages,
        latency_ms=row.latency_ms,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        model=row.model,
        answer=row.answer,
        error=row.error,
        est_cost=row.est_cost,
        feedback=row.feedback,
        created_at=row.created_at,
    )


def _cutoff(retention_days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=retention_days)


async def add_trace(
    tenant_id: UUID,
    user_id: UUID,
    *,
    retention_days: int,
    request_id: str,
    endpoint: str,
    query: str,
    rewritten_query: str | None,
    stages: dict[str, Any],
    latency_ms: dict[str, float],
    prompt_tokens: int | None,
    completion_tokens: int | None,
    model: str | None,
    answer: str | None,
    error: str | None,
    message_id: UUID | None,
    est_cost: Decimal | None = None,
) -> UUID:
    """Store a trace and drop this tenant's traces past retention, in one transaction."""
    async with session_scope() as session:
        await session.execute(
            delete(QueryTrace).where(
                QueryTrace.tenant_id == tenant_id,
                QueryTrace.created_at < _cutoff(retention_days),
            )
        )
        row = QueryTrace(
            tenant_id=tenant_id,
            user_id=user_id,
            request_id=request_id,
            endpoint=endpoint,
            message_id=message_id,
            query=query,
            rewritten_query=rewritten_query,
            stages=stages,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
            answer=answer,
            error=error,
            est_cost=est_cost,
        )
        session.add(row)
        await session.commit()
        return row.id


async def get_by_request_id(tenant_id: UUID, request_id: str) -> TraceRecord | None:
    """The newest trace with this request id in the tenant (a client may reuse an id)."""
    async with session_scope() as session:
        row = await session.scalar(
            select(QueryTrace)
            .where(
                QueryTrace.tenant_id == tenant_id, QueryTrace.request_id == request_id
            )
            .order_by(QueryTrace.created_at.desc(), QueryTrace.id.desc())
            .limit(1)
        )
        return _record(row) if row is not None else None


async def set_feedback(
    tenant_id: UUID, user_id: UUID, message_id: UUID, value: int
) -> bool:
    """Thumbs up (1) or down (-1) on the trace of the caller's own message. False if there is
    no such trace for this user in this tenant."""
    async with session_scope() as session:
        result = await session.execute(
            update(QueryTrace)
            .where(
                QueryTrace.tenant_id == tenant_id,
                QueryTrace.user_id == user_id,
                QueryTrace.message_id == message_id,
            )
            .values(feedback=value)
        )
        await session.commit()
        return cast(CursorResult[Any], result).rowcount > 0


async def purge_expired(retention_days: int) -> int:
    """Delete every tenant's traces past retention; the number deleted."""
    async with session_scope() as session:
        result = await session.execute(
            delete(QueryTrace).where(QueryTrace.created_at < _cutoff(retention_days))
        )
        await session.commit()
        return cast(CursorResult[Any], result).rowcount
