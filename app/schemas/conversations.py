import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import ChatRequest


class ConversationCreate(BaseModel):
    """A new conversation for the caller. Owner and tenant come from the token."""

    title: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": {"title": "Charging questions"}}
    )


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "6a3f1d2e-9b8c-4d7e-a1f0-2b3c4d5e6f70",
                "title": "Charging questions",
                "created_at": "2026-10-09T12:00:00Z",
            }
        }
    )


class ConversationList(BaseModel):
    items: list[ConversationOut]
    total: int
    limit: int
    offset: int


class MessageOut(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    sources: list[dict[str, Any]] | None = Field(
        description="Assistant turns: the numbered sources sent (ids and headings, no text)."
    )
    rewritten_query: str | None = Field(
        description="Assistant turns: the query retrieval actually used."
    )
    model: str | None
    truncated: bool = Field(
        description="True if the answer was cut short (error or client disconnect)."
    )
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationMessageRequest(ChatRequest):
    """A new user turn. Same fields as POST /v1/chat; tenant_id and user_id are rejected."""
