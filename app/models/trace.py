import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class QueryTrace(Base):
    """One chat or conversation answer, reconstructable after the fact (M9 9.1).

    Tenant data: the question and the answer are stored, and the answer can quote document
    text. Retrieval is stored without text: stages hold chunk ids, scores and ranks only.
    Kept TRACE_RETENTION_DAYS; deleted with the conversation message it belongs to.
    """

    __tablename__ = "query_traces"
    __table_args__ = (
        Index("ix_query_traces_tenant_id_request_id", "tenant_id", "request_id"),
        Index("ix_query_traces_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_query_traces_message_id", "message_id"),
        # The user must be a user of this tenant, enforced by the database.
        ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("feedback IN (-1, 1)", name="feedback_is_thumbs"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # "chat" (POST /v1/chat) or "conversation" (a conversation turn, with message_id).
    endpoint: Mapped[str] = mapped_column(String(32), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per retrieval stage: [{chunk_id, score, rank}], ids and numbers only.
    stages: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Milliseconds per span name (app.core.tracing).
    latency_ms: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The error's type or code when the answer failed; never provider text.
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Null on the free local stack (no per-token price).
    est_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    feedback: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
