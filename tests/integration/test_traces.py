"""POST /v1/messages/{id}/feedback and GET /v1/traces/{request_id} (M9 9.1).

Feedback: own messages only. Traces: admins of the trace's tenant only; anyone else gets
the same 404 as a trace that doesn't exist.
"""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.providers.llm import FakeLLM
from app.repositories import trace_repository
from tests.conftest import Caller

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NewTenant = Callable[[], Awaitable[Caller]]
NewMember = Callable[[Caller], Awaitable[Caller]]
QUESTION = "How long does charging take?"


async def _turn(client: AsyncClient, caller: Caller) -> tuple[str, str]:
    """One conversation turn: (assistant message id, the turn's request id)."""
    created = await client.post(
        "/v1/conversations", headers=caller.headers, json={"title": None}
    )
    conversation_id = created.json()["id"]
    turn = await client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=caller.headers,
        json={"question": QUESTION},
    )
    assert turn.status_code == 200, turn.text
    body = (
        await client.get(f"/v1/conversations/{conversation_id}", headers=caller.headers)
    ).json()
    return body["messages"][-1]["id"], turn.headers["x-request-id"]


# --- feedback ------------------------------------------------------------------------


async def test_thumbs_down_on_my_answer_attaches_to_its_trace(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    caller = await new_tenant()
    message_id, request_id = await _turn(client, caller)

    response = await client.post(
        f"/v1/messages/{message_id}/feedback",
        headers=caller.headers,
        json={"value": -1},
    )

    assert response.status_code == 204
    trace = await trace_repository.get_by_request_id(caller.tenant_id, request_id)
    assert trace is not None and trace.feedback == -1


@pytest.mark.parametrize("who", ["member of my tenant", "admin of another tenant"])
async def test_nobody_else_can_rate_my_answer(
    client: AsyncClient,
    new_tenant: NewTenant,
    new_member: NewMember,
    fake_llm: FakeLLM,
    who: str,
) -> None:
    owner = await new_tenant()
    message_id, request_id = await _turn(client, owner)
    other = await new_member(owner) if who.startswith("member") else await new_tenant()

    response = await client.post(
        f"/v1/messages/{message_id}/feedback", headers=other.headers, json={"value": 1}
    )

    assert response.status_code == 404
    trace = await trace_repository.get_by_request_id(owner.tenant_id, request_id)
    assert trace is not None and trace.feedback is None


async def test_feedback_on_an_unknown_message_is_404(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()

    response = await client.post(
        f"/v1/messages/{uuid.uuid4()}/feedback",
        headers=caller.headers,
        json={"value": 1},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [{"value": 0}, {"value": 2}, {"value": "up"}, {}, {"value": 1, "tenant_id": "x"}],
)
async def test_an_invalid_feedback_body_is_422(
    client: AsyncClient, new_tenant: NewTenant, body: dict[str, object]
) -> None:
    caller = await new_tenant()

    response = await client.post(
        f"/v1/messages/{uuid.uuid4()}/feedback", headers=caller.headers, json=body
    )

    assert response.status_code == 422


async def test_feedback_with_a_malformed_message_id_is_422(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()

    response = await client.post(
        "/v1/messages/not-a-uuid/feedback", headers=caller.headers, json={"value": 1}
    )

    assert response.status_code == 422


async def test_feedback_without_a_token_is_401(client: AsyncClient) -> None:
    response = await client.post(
        f"/v1/messages/{uuid.uuid4()}/feedback", json={"value": 1}
    )

    assert response.status_code == 401


# --- traces --------------------------------------------------------------------------


async def test_an_admin_reads_a_trace_of_their_tenant(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    admin = await new_tenant()
    message_id, request_id = await _turn(client, admin)

    response = await client.get(f"/v1/traces/{request_id}", headers=admin.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request_id"] == request_id
    assert (body["endpoint"], body["query"]) == ("conversation", QUESTION)
    assert body["answer"] and body["message_id"] == message_id
    assert body["user_id"] == str(admin.user_id)
    final = [c["chunk_id"] for c in body["stages"]["final"]]
    assert final and set(final) <= set(admin.chunk_ids)
    assert "generate" in body["latency_ms"]
    assert body["est_cost"] is None and body["feedback"] is None


async def test_a_member_gets_404_for_a_trace_of_their_own_tenant(
    client: AsyncClient, new_tenant: NewTenant, new_member: NewMember, fake_llm: FakeLLM
) -> None:
    admin = await new_tenant()
    member = await new_member(admin)
    _, request_id = await _turn(client, member)

    response = await client.get(f"/v1/traces/{request_id}", headers=member.headers)

    assert response.status_code == 404


async def test_another_tenants_admin_gets_the_same_404_as_a_missing_trace(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    owner = await new_tenant()
    _, request_id = await _turn(client, owner)
    other = await new_tenant()

    cross = await client.get(f"/v1/traces/{request_id}", headers=other.headers)
    missing = await client.get("/v1/traces/no-such-request", headers=other.headers)

    assert cross.status_code == missing.status_code == 404
    assert cross.json()["detail"] == missing.json()["detail"]


@pytest.mark.parametrize("bad", ["a" * 129, "has space", "semi;colon"])
async def test_an_invalid_request_id_is_422(
    client: AsyncClient, new_tenant: NewTenant, bad: str
) -> None:
    admin = await new_tenant()

    response = await client.get(f"/v1/traces/{bad}", headers=admin.headers)

    assert response.status_code == 422


async def test_reading_a_trace_without_a_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/v1/traces/anything")

    assert response.status_code == 401
