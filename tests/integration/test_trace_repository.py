"""trace_repository: query traces are tenant data (M9 9.1).

Every read is scoped by tenant; feedback only by the user the trace belongs to; old traces
are purged after the retention period.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import update

from app.models.conversation import MessageRole
from app.models.trace import QueryTrace
from app.models.user import User, UserRole
from app.repositories import auth_repository, conversation_repository, trace_repository
from app.repositories.session import session_scope

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def _tenant_user() -> tuple[UUID, UUID]:
    tenant, user = await auth_repository.create_tenant_and_admin_user(
        f"tenant-{uuid.uuid4().hex}", f"user-{uuid.uuid4().hex}@example.com", "hash"
    )
    return tenant.id, user.id


async def _member_of(tenant_id: UUID) -> UUID:
    async with session_scope() as session:
        member = User(
            tenant_id=tenant_id,
            email=f"member-{uuid.uuid4().hex}@example.com",
            password_hash="hash",
            role=UserRole.member,
        )
        session.add(member)
        await session.commit()
        return member.id


def _fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "request_id": f"req-{uuid.uuid4().hex}",
        "endpoint": "chat",
        "query": "How long does charging take?",
        "rewritten_query": None,
        "stages": {"final": [{"chunk_id": str(uuid.uuid4()), "score": 0.9, "rank": 1}]},
        "latency_ms": {"rerank": 12.5, "generate": 3000.0},
        "prompt_tokens": 420,
        "completion_tokens": 12,
        "model": "llama3.2:3b",
        "answer": "Two hours [1].",
        "error": None,
        "message_id": None,
    }
    fields.update(overrides)
    return fields


async def test_a_trace_is_stored_and_read_back_by_request_id_in_its_tenant() -> None:
    tenant, user = await _tenant_user()
    fields = _fields()

    await trace_repository.add_trace(tenant, user, retention_days=30, **fields)
    found = await trace_repository.get_by_request_id(tenant, fields["request_id"])

    assert found is not None
    assert (found.query, found.answer, found.model) == (
        fields["query"],
        fields["answer"],
        "llama3.2:3b",
    )
    assert found.stages == fields["stages"]
    assert found.latency_ms == fields["latency_ms"]
    assert (found.prompt_tokens, found.completion_tokens) == (420, 12)
    assert found.est_cost is None and found.feedback is None
    assert found.user_id == user


async def test_another_tenant_cannot_read_a_trace_even_with_its_request_id() -> None:
    tenant, user = await _tenant_user()
    other, _ = await _tenant_user()
    fields = _fields()
    await trace_repository.add_trace(tenant, user, retention_days=30, **fields)

    assert await trace_repository.get_by_request_id(other, fields["request_id"]) is None


async def test_a_reused_request_id_returns_the_newest_trace() -> None:
    tenant, user = await _tenant_user()
    await trace_repository.add_trace(
        tenant, user, retention_days=30, **_fields(request_id="same", answer="old")
    )
    await trace_repository.add_trace(
        tenant, user, retention_days=30, **_fields(request_id="same", answer="new")
    )

    found = await trace_repository.get_by_request_id(tenant, "same")

    assert found is not None and found.answer == "new"


async def _message(tenant: UUID, user: UUID) -> UUID:
    conversation = await conversation_repository.create_conversation(tenant, user, None)
    message = await conversation_repository.add_message(
        tenant, user, conversation.id, role=MessageRole.assistant, content="a"
    )
    assert message is not None
    return message.id


async def test_feedback_attaches_to_the_trace_of_my_own_message() -> None:
    tenant, user = await _tenant_user()
    message_id = await _message(tenant, user)
    fields = _fields(endpoint="conversation", message_id=message_id)
    await trace_repository.add_trace(tenant, user, retention_days=30, **fields)

    assert await trace_repository.set_feedback(tenant, user, message_id, -1) is True
    found = await trace_repository.get_by_request_id(tenant, fields["request_id"])

    assert found is not None and found.feedback == -1


@pytest.mark.parametrize("who", ["other user, same tenant", "other tenant"])
async def test_nobody_else_can_give_feedback_on_my_message(who: str) -> None:
    tenant, user = await _tenant_user()
    message_id = await _message(tenant, user)
    fields = _fields(endpoint="conversation", message_id=message_id)
    await trace_repository.add_trace(tenant, user, retention_days=30, **fields)
    if who == "other tenant":
        caller_tenant, caller = await _tenant_user()
    else:
        caller_tenant, caller = tenant, await _member_of(tenant)

    assert (
        await trace_repository.set_feedback(caller_tenant, caller, message_id, 1)
        is False
    )
    found = await trace_repository.get_by_request_id(tenant, fields["request_id"])
    assert found is not None and found.feedback is None


async def test_deleting_the_conversation_deletes_its_traces() -> None:
    tenant, user = await _tenant_user()
    conversation = await conversation_repository.create_conversation(tenant, user, None)
    message = await conversation_repository.add_message(
        tenant, user, conversation.id, role=MessageRole.assistant, content="a"
    )
    assert message is not None
    fields = _fields(endpoint="conversation", message_id=message.id)
    await trace_repository.add_trace(tenant, user, retention_days=30, **fields)

    await conversation_repository.delete_conversation(tenant, user, conversation.id)

    assert (
        await trace_repository.get_by_request_id(tenant, fields["request_id"]) is None
    )


async def _age(request_id: str, days: int) -> None:
    async with session_scope() as session:
        await session.execute(
            update(QueryTrace)
            .where(QueryTrace.request_id == request_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=days))
        )
        await session.commit()


async def test_writing_a_trace_purges_that_tenants_traces_past_retention() -> None:
    tenant, user = await _tenant_user()
    other, other_user = await _tenant_user()
    old, kept, others = _fields(), _fields(), _fields()
    await trace_repository.add_trace(tenant, user, retention_days=30, **old)
    await trace_repository.add_trace(tenant, user, retention_days=30, **kept)
    await trace_repository.add_trace(other, other_user, retention_days=30, **others)
    await _age(old["request_id"], 31)
    await _age(kept["request_id"], 29)
    await _age(others["request_id"], 31)

    await trace_repository.add_trace(tenant, user, retention_days=30, **_fields())

    assert await trace_repository.get_by_request_id(tenant, old["request_id"]) is None
    assert (
        await trace_repository.get_by_request_id(tenant, kept["request_id"]) is not None
    )
    # Another tenant's old trace waits for its own next write, or the global purge.
    assert (
        await trace_repository.get_by_request_id(other, others["request_id"])
        is not None
    )
    assert await trace_repository.purge_expired(retention_days=30) >= 1
    assert await trace_repository.get_by_request_id(other, others["request_id"]) is None
