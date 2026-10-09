"""IDOR suite for /v1/conversations (guide 6.4, ADR-0009).

Another user in the same tenant, a tenant admin, and another tenant all get 404 for every
operation on a conversation they don't own, with the same body as a conversation that
doesn't exist, so existence never leaks. Each test first proves the owner gets 200 on the
very same request, so a missing route (also 404) can't make it pass.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select

from app.models.conversation import Message
from app.providers.llm import FakeLLM
from app.repositories.session import session_scope
from tests.conftest import Caller

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NewTenant = Callable[[], Awaitable[Caller]]
NewMember = Callable[[Caller], Awaitable[Caller]]
QUESTION = {"question": "How long does charging take?"}


async def _conversation(client: AsyncClient, owner: Caller) -> str:
    created = await client.post(
        "/v1/conversations", headers=owner.headers, json={"title": "mine"}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _events(response: Response) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for frame in response.text.split("\n\n"):
        if frame.strip():
            lines = dict(line.split(": ", 1) for line in frame.split("\n"))
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def _same_problem(theirs: Response, missing: Response) -> bool:
    """Identical bodies apart from each response's own request_id (M7 problem+json)."""
    for response in (theirs, missing):
        assert response.json()["request_id"] == response.headers["x-request-id"]
    a, b = dict(theirs.json()), dict(missing.json())
    a.pop("request_id"), b.pop("request_id")
    return a == b


async def _message_count(conversation_id: str) -> int:
    async with session_scope() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == uuid.UUID(conversation_id))
        )
        return int(count or 0)


async def _intruder(
    kind: str, owner: Caller, new_tenant: NewTenant, new_member: NewMember
) -> Caller:
    if kind == "other_user":
        return await new_member(owner)
    if kind == "admin_of_my_tenant":
        # The owner is a member; the tenant's admin (the signup user) is the intruder.
        return owner
    return await new_tenant()


async def _owner_and_intruder(
    kind: str, new_tenant: NewTenant, new_member: NewMember
) -> tuple[Caller, Caller]:
    first = await new_tenant()
    if kind == "admin_of_my_tenant":
        member = await new_member(first)
        return member, first
    return first, await _intruder(kind, first, new_tenant, new_member)


INTRUDERS = ["other_user", "admin_of_my_tenant", "other_tenant"]


@pytest.mark.parametrize("kind", INTRUDERS)
async def test_get_of_someone_elses_conversation_is_404_like_a_missing_one(
    client: AsyncClient, new_tenant: NewTenant, new_member: NewMember, kind: str
) -> None:
    owner, intruder = await _owner_and_intruder(kind, new_tenant, new_member)
    conversation_id = await _conversation(client, owner)
    url = f"/v1/conversations/{conversation_id}"
    assert (await client.get(url, headers=owner.headers)).status_code == 200

    theirs = await client.get(url, headers=intruder.headers)
    missing = await client.get(
        f"/v1/conversations/{uuid.uuid4()}", headers=intruder.headers
    )

    assert theirs.status_code == 404
    assert _same_problem(theirs, missing)


@pytest.mark.parametrize("kind", INTRUDERS)
async def test_posting_to_someone_elses_conversation_is_404_and_writes_nothing(
    client: AsyncClient,
    new_tenant: NewTenant,
    new_member: NewMember,
    fake_llm: FakeLLM,
    kind: str,
) -> None:
    owner, intruder = await _owner_and_intruder(kind, new_tenant, new_member)
    conversation_id = await _conversation(client, owner)
    url = f"/v1/conversations/{conversation_id}/messages"
    mine = await client.post(url, headers=owner.headers, json=QUESTION)
    assert mine.status_code == 200, mine.text
    before = await _message_count(conversation_id)
    calls = len(fake_llm.calls)

    theirs = await client.post(url, headers=intruder.headers, json=QUESTION)
    missing = await client.post(
        f"/v1/conversations/{uuid.uuid4()}/messages",
        headers=intruder.headers,
        json=QUESTION,
    )

    assert theirs.status_code == 404
    assert _same_problem(theirs, missing)
    assert await _message_count(conversation_id) == before
    assert len(fake_llm.calls) == calls


@pytest.mark.parametrize("kind", INTRUDERS)
async def test_deleting_someone_elses_conversation_is_404_and_it_survives(
    client: AsyncClient, new_tenant: NewTenant, new_member: NewMember, kind: str
) -> None:
    owner, intruder = await _owner_and_intruder(kind, new_tenant, new_member)
    conversation_id = await _conversation(client, owner)
    url = f"/v1/conversations/{conversation_id}"

    theirs = await client.delete(url, headers=intruder.headers)
    missing = await client.delete(
        f"/v1/conversations/{uuid.uuid4()}", headers=intruder.headers
    )

    assert theirs.status_code == 404
    assert _same_problem(theirs, missing)
    assert (await client.get(url, headers=owner.headers)).status_code == 200
    assert (await client.delete(url, headers=owner.headers)).status_code == 204


@pytest.mark.parametrize("kind", INTRUDERS)
async def test_listing_shows_only_my_own_conversations(
    client: AsyncClient, new_tenant: NewTenant, new_member: NewMember, kind: str
) -> None:
    owner, intruder = await _owner_and_intruder(kind, new_tenant, new_member)
    mine = await _conversation(client, owner)
    theirs = await _conversation(client, intruder)

    my_list = await client.get("/v1/conversations", headers=owner.headers)
    their_list = await client.get("/v1/conversations", headers=intruder.headers)

    assert my_list.status_code == 200
    assert [c["id"] for c in my_list.json()["items"]] == [mine]
    assert my_list.json()["total"] == 1
    assert [c["id"] for c in their_list.json()["items"]] == [theirs]


async def test_deleting_my_conversation_deletes_its_messages(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    owner = await new_tenant()
    conversation_id = await _conversation(client, owner)
    url = f"/v1/conversations/{conversation_id}"
    await client.post(f"{url}/messages", headers=owner.headers, json=QUESTION)
    assert await _message_count(conversation_id) == 2

    assert (await client.delete(url, headers=owner.headers)).status_code == 204

    assert (await client.get(url, headers=owner.headers)).status_code == 404
    assert await _message_count(conversation_id) == 0


async def test_a_rewritten_follow_up_never_retrieves_another_tenants_chunks(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    # Identical documents in both tenants, in one collection.
    tenant_a = await new_tenant()
    tenant_b = await new_tenant()
    conversation_id = await _conversation(client, tenant_b)
    url = f"/v1/conversations/{conversation_id}/messages"
    await client.post(url, headers=tenant_b.headers, json=QUESTION)

    follow_up = await client.post(
        url, headers=tenant_b.headers, json={"question": "And how do I calibrate it?"}
    )

    sources = _events(follow_up)[0][1]
    assert sources["rewritten_query"] == (
        "How long does charging take? And how do I calibrate it?"
    )
    returned = {s["chunk_id"] for s in sources["sources"]}
    assert returned and returned <= set(tenant_b.chunk_ids)
    assert not returned & set(tenant_a.chunk_ids)


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/v1/conversations"),
        ("get", "/v1/conversations"),
        ("get", "/v1/conversations/{id}"),
        ("post", "/v1/conversations/{id}/messages"),
        ("delete", "/v1/conversations/{id}"),
    ],
)
async def test_every_conversation_endpoint_without_a_token_is_401(
    client: AsyncClient, new_tenant: NewTenant, method: str, path: str
) -> None:
    owner = await new_tenant()
    conversation_id = await _conversation(client, owner)
    body = QUESTION if path.endswith("messages") else {"title": "x"}
    url = path.format(id=conversation_id)

    response = await client.request(
        method.upper(), url, json=body if method == "post" else None
    )

    assert response.status_code == 401
