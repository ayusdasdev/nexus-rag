"""Conversations and messages. Every query is scoped by tenant_id AND user_id.

A conversation owned by someone else is indistinguishable from one that doesn't exist:
functions return None or False for both, so the API answers 404 either way.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult

from app.models.conversation import Conversation, Message, MessageRole
from app.repositories.session import session_scope


@dataclass(frozen=True)
class ConversationRecord:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    title: str | None
    created_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    sources: list[dict[str, Any]] | None
    rewritten_query: str | None
    model: str | None
    usage: dict[str, Any] | None
    truncated: bool
    created_at: datetime


def _conversation(row: Conversation) -> ConversationRecord:
    return ConversationRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        title=row.title,
        created_at=row.created_at,
    )


def _message(row: Message) -> MessageRecord:
    return MessageRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        role=row.role.value,
        content=row.content,
        sources=row.sources,
        rewritten_query=row.rewritten_query,
        model=row.model,
        usage=row.usage,
        truncated=row.truncated,
        created_at=row.created_at,
    )


def _owned(tenant_id: UUID, user_id: UUID, conversation_id: UUID) -> Any:
    return (
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
        Conversation.user_id == user_id,
    )


async def create_conversation(
    tenant_id: UUID, user_id: UUID, title: str | None
) -> ConversationRecord:
    async with session_scope() as session:
        row = Conversation(tenant_id=tenant_id, user_id=user_id, title=title)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _conversation(row)


async def get_conversation(
    tenant_id: UUID, user_id: UUID, conversation_id: UUID
) -> ConversationRecord | None:
    async with session_scope() as session:
        row = await session.scalar(
            select(Conversation).where(*_owned(tenant_id, user_id, conversation_id))
        )
        return _conversation(row) if row is not None else None


async def list_conversations(
    tenant_id: UUID, user_id: UUID, limit: int, offset: int
) -> tuple[list[ConversationRecord], int]:
    """The caller's own conversations, newest first, and how many there are in total."""
    scope = (Conversation.tenant_id == tenant_id, Conversation.user_id == user_id)
    async with session_scope() as session:
        total = await session.scalar(
            select(func.count()).select_from(Conversation).where(*scope)
        )
        result = await session.execute(
            select(Conversation)
            .where(*scope)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_conversation(row) for row in result.scalars().all()], int(total or 0)


async def delete_conversation(
    tenant_id: UUID, user_id: UUID, conversation_id: UUID
) -> bool:
    """Delete the caller's conversation and (by cascade) its messages. False if not theirs."""
    async with session_scope() as session:
        result = cast(
            CursorResult[Any],
            await session.execute(
                delete(Conversation).where(*_owned(tenant_id, user_id, conversation_id))
            ),
        )
        await session.commit()
        return result.rowcount == 1


async def list_messages(
    tenant_id: UUID, user_id: UUID, conversation_id: UUID
) -> list[MessageRecord] | None:
    """Messages of the caller's conversation, oldest first. None if not theirs."""
    async with session_scope() as session:
        owned = await session.scalar(
            select(Conversation.id).where(*_owned(tenant_id, user_id, conversation_id))
        )
        if owned is None:
            return None
        result = await session.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.tenant_id == tenant_id,
            )
            .order_by(Message.created_at, Message.id)
        )
        return [_message(row) for row in result.scalars().all()]


async def add_message(
    tenant_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    *,
    role: MessageRole,
    content: str,
    sources: list[dict[str, Any]] | None = None,
    rewritten_query: str | None = None,
    model: str | None = None,
    usage: dict[str, Any] | None = None,
    truncated: bool = False,
) -> MessageRecord | None:
    """Append to the caller's conversation. None (and nothing written) if not theirs."""
    async with session_scope() as session:
        owned = await session.scalar(
            select(Conversation.id).where(*_owned(tenant_id, user_id, conversation_id))
        )
        if owned is None:
            return None
        row = Message(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            role=role,
            content=content,
            sources=sources,
            rewritten_query=rewritten_query,
            model=model,
            usage=usage,
            truncated=truncated,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _message(row)
