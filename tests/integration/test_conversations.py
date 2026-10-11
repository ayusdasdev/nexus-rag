"""/v1/conversations: create, list, get, messages (SSE) and delete, for the owner.

Ownership across users and tenants is in test_conversations_idor.py.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.core.config import Settings, get_settings
from app.main import app
from app.providers.llm import FakeLLM
from tests.conftest import Caller

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NewTenant = Callable[[], Awaitable[Caller]]
Q1 = "How long does charging take?"
Q2 = "And how do I calibrate it?"


def _events(response: Response) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for frame in response.text.split("\n\n"):
        if frame.strip():
            lines = dict(line.split(": ", 1) for line in frame.split("\n"))
            events.append((lines["event"], json.loads(lines["data"])))
    return events


async def _create(
    client: AsyncClient, caller: Caller, title: str | None = "Charging"
) -> str:
    response = await client.post(
        "/v1/conversations", headers=caller.headers, json={"title": title}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_create_returns_201_with_the_conversation(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()

    response = await client.post(
        "/v1/conversations", headers=caller.headers, json={"title": "Charging"}
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "title", "created_at"}
    assert body["title"] == "Charging"


async def test_create_without_a_title_is_allowed(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()

    response = await client.post("/v1/conversations", headers=caller.headers, json={})

    assert response.status_code == 201
    assert response.json()["title"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"title": "x" * 201},
        {"title": "ok", "tenant_id": str(uuid.uuid4())},
        {"title": "ok", "user_id": str(uuid.uuid4())},
    ],
    ids=["title-too-long", "tenant-id", "user-id"],
)
async def test_create_with_an_invalid_body_is_422(
    client: AsyncClient, new_tenant: NewTenant, body: dict[str, Any]
) -> None:
    caller = await new_tenant()

    response = await client.post("/v1/conversations", headers=caller.headers, json=body)

    assert response.status_code == 422


async def test_list_is_paginated_newest_first(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()
    ids = [await _create(client, caller, f"c{n}") for n in range(3)]

    page = await client.get(
        "/v1/conversations", headers=caller.headers, params={"limit": 2}
    )
    rest = await client.get(
        "/v1/conversations",
        headers=caller.headers,
        params={"limit": 2, "after": page.json()["next_cursor"]},
    )

    assert page.status_code == 200
    assert [c["id"] for c in page.json()["items"]] == [ids[2], ids[1]]
    assert page.json()["total"] == 3
    assert [c["id"] for c in rest.json()["items"]] == [ids[0]]


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"after": "not-a-cursor"}]
)
async def test_list_with_bad_paging_is_422(
    client: AsyncClient, new_tenant: NewTenant, params: dict[str, int]
) -> None:
    caller = await new_tenant()

    response = await client.get(
        "/v1/conversations", headers=caller.headers, params=params
    )

    assert response.status_code == 422


async def test_a_turn_streams_like_chat_and_persists_both_messages(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    caller = await new_tenant()
    conversation_id = await _create(client, caller)
    url = f"/v1/conversations/{conversation_id}"

    response = await client.post(
        f"{url}/messages", headers=caller.headers, json={"question": Q1}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = _events(response)
    assert [name for name, _ in events] == [
        "sources",
        "token",
        "token",
        "citations",
        "done",
    ]
    # First turn: nothing to rewrite, so retrieval used the question itself.
    assert events[0][1]["rewritten_query"] == Q1
    assert events[-1][1]["answer"] == "Two hours [1]."

    detail = (await client.get(url, headers=caller.headers)).json()
    user, assistant = detail["messages"]
    assert (user["role"], user["content"]) == ("user", Q1)
    assert (assistant["role"], assistant["content"]) == ("assistant", "Two hours [1].")
    assert assistant["rewritten_query"] == Q1
    assert assistant["model"] == "fake"
    assert assistant["truncated"] is False
    assert assistant["sources"] and all("text" not in s for s in assistant["sources"])
    assert {s["chunk_id"] for s in assistant["sources"]} <= set(caller.chunk_ids)


async def test_the_second_turn_is_rewritten_by_rule_and_sees_the_history(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    caller = await new_tenant()
    url = f"/v1/conversations/{await _create(client, caller)}/messages"
    await client.post(url, headers=caller.headers, json={"question": Q1})

    second = await client.post(url, headers=caller.headers, json={"question": Q2})

    assert _events(second)[0][1]["rewritten_query"] == f"{Q1} {Q2}"
    prompt = fake_llm.calls[-1]
    assert [m.role for m in prompt] == ["system", "user", "assistant", "user"]
    assert prompt[1].content == Q1
    # Old [N] numbers are stripped from resent answers (M6 review, LOW-2).
    assert prompt[2].content == "Two hours."
    assert f"<question>\n{Q2}\n</question>" in prompt[3].content


async def test_rewrite_mode_off_retrieves_with_the_question_as_is(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    caller = await new_tenant()
    url = f"/v1/conversations/{await _create(client, caller)}/messages"
    await client.post(url, headers=caller.headers, json={"question": Q1})
    app.dependency_overrides[get_settings] = lambda: Settings(rewrite_mode="off")
    try:
        second = await client.post(url, headers=caller.headers, json={"question": Q2})
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert _events(second)[0][1]["rewritten_query"] == Q2


@pytest.mark.parametrize(
    "body",
    [{}, {"question": ""}, {"question": Q1, "tenant_id": str(uuid.uuid4())}],
    ids=["missing", "empty", "tenant-id"],
)
async def test_a_message_with_an_invalid_body_is_422_and_saves_nothing(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM, body: dict[str, Any]
) -> None:
    caller = await new_tenant()
    url = f"/v1/conversations/{await _create(client, caller)}"

    response = await client.post(f"{url}/messages", headers=caller.headers, json=body)

    assert response.status_code == 422
    assert (await client.get(url, headers=caller.headers)).json()["messages"] == []
    assert fake_llm.calls == []


async def test_delete_returns_204_and_the_conversation_is_gone(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()
    url = f"/v1/conversations/{await _create(client, caller)}"

    response = await client.delete(url, headers=caller.headers)

    assert response.status_code == 204
    assert (await client.get(url, headers=caller.headers)).status_code == 404


async def test_a_malformed_conversation_id_is_422(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()

    response = await client.get("/v1/conversations/not-a-uuid", headers=caller.headers)

    assert response.status_code == 422


# --- M6 review, MEDIUM-3: pagination and caps -------------------------------------


async def test_get_pages_messages_and_reports_their_total(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    caller = await new_tenant()
    url = f"/v1/conversations/{await _create(client, caller)}"
    await client.post(f"{url}/messages", headers=caller.headers, json={"question": Q1})

    first = await client.get(url, headers=caller.headers, params={"limit": 1})
    page = await client.get(
        url,
        headers=caller.headers,
        params={"limit": 1, "after": first.json()["next_cursor"]},
    )

    assert page.status_code == 200
    assert [m["role"] for m in first.json()["messages"]] == ["user"]
    assert [m["role"] for m in page.json()["messages"]] == ["assistant"]
    assert page.json()["messages_total"] == 2
    assert page.json()["next_cursor"] is None


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 501}, {"after": "not-a-cursor"}]
)
async def test_get_with_bad_message_paging_is_422(
    client: AsyncClient, new_tenant: NewTenant, params: dict[str, int]
) -> None:
    caller = await new_tenant()
    url = f"/v1/conversations/{await _create(client, caller)}"

    assert (
        await client.get(url, headers=caller.headers, params=params)
    ).status_code == 422


async def test_a_conversation_at_its_message_cap_refuses_a_turn_with_409(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    caller = await new_tenant()
    url = f"/v1/conversations/{await _create(client, caller)}"
    app.dependency_overrides[get_settings] = lambda: Settings(
        conversation_max_messages=2
    )
    try:
        first = await client.post(
            f"{url}/messages", headers=caller.headers, json={"question": Q1}
        )
        calls = len(fake_llm.calls)
        second = await client.post(
            f"{url}/messages", headers=caller.headers, json={"question": Q2}
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert first.status_code == 200
    assert second.status_code == 409
    assert len(fake_llm.calls) == calls
    assert (await client.get(url, headers=caller.headers)).json()["messages_total"] == 2


async def test_a_user_at_the_conversation_cap_gets_409_on_create(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()
    app.dependency_overrides[get_settings] = lambda: Settings(
        max_conversations_per_user=1
    )
    try:
        first = await client.post("/v1/conversations", headers=caller.headers, json={})
        second = await client.post("/v1/conversations", headers=caller.headers, json={})
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert first.status_code == 201
    assert second.status_code == 409


async def test_a_conversation_deleted_mid_request_is_404_not_an_orphan_answer(
    client: AsyncClient,
    new_tenant: NewTenant,
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # M6 review, LOW-1: the ownership check passed, then the conversation vanished before
    # the user turn was saved; nothing should be retrieved, generated or streamed.
    from app.repositories import conversation_repository

    caller = await new_tenant()
    url = f"/v1/conversations/{await _create(client, caller)}"

    async def vanished(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(conversation_repository, "add_message", vanished)

    response = await client.post(
        f"{url}/messages", headers=caller.headers, json={"question": Q1}
    )

    assert response.status_code == 404
    assert fake_llm.calls == []


# --- a wall clock that steps backwards (M8: the flaky second-turn failure) -----------
# Seen 2026-10-11 08:57: turn 1's user message got created_at 0.65 s *after* its own
# answer and after both turn-2 messages (Postgres now() is each transaction's start time,
# and the WSL2 / Docker clock stepped back). Ordered by created_at, turn 1 came back as
# (assistant, user), so the pairing dropped it and turn 2 saw no history.


def _clock_ahead_while_the_first_question_is_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The clock step: the first question is stored 1 hour in the future, as if the clock was
    ahead then and stepped back before the answer was saved."""
    from sqlalchemy import text

    from app.repositories import conversation_repository
    from app.repositories.session import session_scope

    original = conversation_repository.add_message
    stepped: list[uuid.UUID] = []

    async def add_message(*args: Any, **kwargs: Any) -> Any:
        record = await original(*args, **kwargs)
        if record is not None and kwargs["role"].value == "user" and not stepped:
            stepped.append(record.id)
            async with session_scope() as session:
                await session.execute(
                    text(
                        "update messages set created_at = created_at"
                        " + interval '1 hour' where id = :id"
                    ),
                    {"id": record.id},
                )
                await session.commit()
        return record

    monkeypatch.setattr(conversation_repository, "add_message", add_message)


async def test_history_survives_a_clock_step_between_the_turns_messages(
    client: AsyncClient,
    new_tenant: NewTenant,
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = await new_tenant()
    conversation_id = await _create(client, caller)
    url = f"/v1/conversations/{conversation_id}/messages"
    _clock_ahead_while_the_first_question_is_saved(monkeypatch)
    await client.post(url, headers=caller.headers, json={"question": Q1})

    second = await client.post(url, headers=caller.headers, json={"question": Q2})

    assert _events(second)[0][1]["rewritten_query"] == f"{Q1} {Q2}"
    assert [m.role for m in fake_llm.calls[-1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


async def test_messages_are_listed_in_the_order_they_were_added_despite_a_clock_step(
    client: AsyncClient,
    new_tenant: NewTenant,
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = await new_tenant()
    conversation_id = await _create(client, caller)
    url = f"/v1/conversations/{conversation_id}/messages"
    _clock_ahead_while_the_first_question_is_saved(monkeypatch)
    await client.post(url, headers=caller.headers, json={"question": Q1})
    await client.post(url, headers=caller.headers, json={"question": Q2})

    body = (
        await client.get(f"/v1/conversations/{conversation_id}", headers=caller.headers)
    ).json()

    assert [(m["role"], m["content"]) for m in body["messages"]][::2] == [
        ("user", Q1),
        ("user", Q2),
    ]
    assert [m["role"] for m in body["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
