"""conversation_repository: every query is scoped by tenant_id AND user_id.

A conversation that exists but belongs to someone else must look exactly like one that
doesn't exist (None / False), so the API can answer 404 for both.
"""

import uuid
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.conversation import Message, MessageRole
from app.models.user import User, UserRole
from app.repositories import auth_repository, conversation_repository
from app.repositories.session import session_scope

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def _tenant_user() -> tuple[UUID, UUID]:
    tenant, user = await auth_repository.create_tenant_and_admin_user(
        f"tenant-{uuid.uuid4().hex}", f"user-{uuid.uuid4().hex}@example.com", "hash"
    )
    return tenant.id, user.id


async def _second_user(tenant_id: UUID) -> UUID:
    async with session_scope() as session:
        user = User(
            tenant_id=tenant_id,
            email=f"member-{uuid.uuid4().hex}@example.com",
            password_hash="hash",
            role=UserRole.member,
        )
        session.add(user)
        await session.commit()
        return user.id


async def _message_count(conversation_id: UUID) -> int:
    async with session_scope() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        return int(count or 0)


async def test_create_then_get_my_conversation() -> None:
    tenant, user = await _tenant_user()

    created = await conversation_repository.create_conversation(
        tenant, user, "Charging"
    )
    fetched = await conversation_repository.get_conversation(tenant, user, created.id)

    assert fetched == created
    assert (fetched.tenant_id, fetched.user_id, fetched.title) == (
        tenant,
        user,
        "Charging",
    )


async def test_another_user_in_my_tenant_cannot_get_my_conversation() -> None:
    tenant, owner = await _tenant_user()
    other = await _second_user(tenant)
    mine = await conversation_repository.create_conversation(tenant, owner, "mine")

    assert (
        await conversation_repository.get_conversation(tenant, other, mine.id) is None
    )


async def test_another_tenant_cannot_get_my_conversation_even_with_my_user_id() -> None:
    tenant, owner = await _tenant_user()
    other_tenant, _ = await _tenant_user()
    mine = await conversation_repository.create_conversation(tenant, owner, "mine")

    assert (
        await conversation_repository.get_conversation(other_tenant, owner, mine.id)
        is None
    )


async def test_a_conversation_that_does_not_exist_is_none() -> None:
    tenant, user = await _tenant_user()

    assert (
        await conversation_repository.get_conversation(tenant, user, uuid.uuid4())
        is None
    )


async def test_listing_returns_only_my_conversations_newest_first() -> None:
    tenant, me = await _tenant_user()
    colleague = await _second_user(tenant)
    other_tenant, stranger = await _tenant_user()
    first = await conversation_repository.create_conversation(tenant, me, "first")
    second = await conversation_repository.create_conversation(tenant, me, "second")
    await conversation_repository.create_conversation(tenant, colleague, "colleague's")
    await conversation_repository.create_conversation(
        other_tenant, stranger, "stranger's"
    )

    records, total = await conversation_repository.list_conversations(
        tenant, me, limit=10, offset=0
    )

    assert [r.id for r in records] == [second.id, first.id]
    assert total == 2


async def test_another_user_cannot_delete_my_conversation_and_it_survives() -> None:
    tenant, owner = await _tenant_user()
    other = await _second_user(tenant)
    mine = await conversation_repository.create_conversation(tenant, owner, "mine")

    assert (
        await conversation_repository.delete_conversation(tenant, other, mine.id)
        is False
    )
    assert (
        await conversation_repository.get_conversation(tenant, owner, mine.id)
        is not None
    )


async def test_deleting_my_conversation_deletes_its_messages() -> None:
    tenant, owner = await _tenant_user()
    mine = await conversation_repository.create_conversation(tenant, owner, "mine")
    await conversation_repository.add_message(
        tenant, owner, mine.id, role=MessageRole.user, content="q"
    )
    await conversation_repository.add_message(
        tenant, owner, mine.id, role=MessageRole.assistant, content="a"
    )
    assert await _message_count(mine.id) == 2

    assert (
        await conversation_repository.delete_conversation(tenant, owner, mine.id)
        is True
    )

    assert (
        await conversation_repository.get_conversation(tenant, owner, mine.id) is None
    )
    assert await _message_count(mine.id) == 0


async def test_messages_come_back_in_order_with_their_metadata() -> None:
    tenant, owner = await _tenant_user()
    mine = await conversation_repository.create_conversation(tenant, owner, None)
    await conversation_repository.add_message(
        tenant, owner, mine.id, role=MessageRole.user, content="How long?"
    )
    await conversation_repository.add_message(
        tenant,
        owner,
        mine.id,
        role=MessageRole.assistant,
        content="Two hours [1].",
        sources=[{"number": 1, "chunk_id": "c"}],
        rewritten_query="How long does charging take?",
        model="llama3.2:3b",
        usage={"output_tokens": 5},
        truncated=True,
    )

    messages = await conversation_repository.list_messages(tenant, owner, mine.id)

    assert messages is not None
    assert [(m.role, m.content) for m in messages] == [
        ("user", "How long?"),
        ("assistant", "Two hours [1]."),
    ]
    reply = messages[1]
    assert reply.sources == [{"number": 1, "chunk_id": "c"}]
    assert reply.rewritten_query == "How long does charging take?"
    assert (reply.model, reply.usage, reply.truncated) == (
        "llama3.2:3b",
        {"output_tokens": 5},
        True,
    )
    assert messages[0].truncated is False


async def test_another_user_cannot_read_my_messages() -> None:
    tenant, owner = await _tenant_user()
    other = await _second_user(tenant)
    mine = await conversation_repository.create_conversation(tenant, owner, "mine")
    await conversation_repository.add_message(
        tenant, owner, mine.id, role=MessageRole.user, content="secret question"
    )

    assert await conversation_repository.list_messages(tenant, other, mine.id) is None


@pytest.mark.parametrize("who", ["other_user", "other_tenant"])
async def test_nobody_else_can_add_a_message_to_my_conversation(who: str) -> None:
    tenant, owner = await _tenant_user()
    mine = await conversation_repository.create_conversation(tenant, owner, "mine")
    if who == "other_user":
        caller_tenant, caller = tenant, await _second_user(tenant)
    else:
        caller_tenant, caller = await _tenant_user()

    added = await conversation_repository.add_message(
        caller_tenant, caller, mine.id, role=MessageRole.user, content="injected"
    )

    assert added is None
    assert await _message_count(mine.id) == 0


async def test_the_database_rejects_a_message_filed_under_another_tenant() -> None:
    tenant, owner = await _tenant_user()
    other_tenant, _ = await _tenant_user()
    mine = await conversation_repository.create_conversation(tenant, owner, "mine")

    with pytest.raises(IntegrityError):
        async with session_scope() as session:
            session.add(
                Message(
                    conversation_id=mine.id,
                    tenant_id=other_tenant,
                    role=MessageRole.user,
                    content="wrong tenant",
                )
            )
            await session.commit()


@pytest.mark.parametrize("operation", ["delete", "list_messages", "add_message"])
async def test_my_user_id_under_another_tenant_reaches_nothing(operation: str) -> None:
    # Defence in depth: tenant_id is checked on every operation, not implied by user_id.
    tenant, owner = await _tenant_user()
    other_tenant, _ = await _tenant_user()
    mine = await conversation_repository.create_conversation(tenant, owner, "mine")

    if operation == "delete":
        assert (
            await conversation_repository.delete_conversation(
                other_tenant, owner, mine.id
            )
            is False
        )
    elif operation == "list_messages":
        assert (
            await conversation_repository.list_messages(other_tenant, owner, mine.id)
            is None
        )
    else:
        added = await conversation_repository.add_message(
            other_tenant, owner, mine.id, role=MessageRole.user, content="x"
        )
        assert added is None
    assert (
        await conversation_repository.get_conversation(tenant, owner, mine.id)
        is not None
    )
    assert await _message_count(mine.id) == 0


async def test_a_message_without_sources_or_usage_stores_sql_null_not_json_null() -> (
    None
):
    # Seen in the M6 6.5 run: None was stored as the JSON value null, so IS NULL missed it.
    tenant, owner = await _tenant_user()
    mine = await conversation_repository.create_conversation(tenant, owner, None)
    added = await conversation_repository.add_message(
        tenant, owner, mine.id, role=MessageRole.user, content="q"
    )
    assert added is not None

    async with session_scope() as session:
        row = (
            await session.execute(
                select(Message.sources.is_(None), Message.usage.is_(None)).where(
                    Message.id == added.id
                )
            )
        ).one()

    assert tuple(row) == (True, True)
