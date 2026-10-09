"""Cursor pagination on documents, chunks, conversations and conversation messages (M7).

Cursors are opaque, signed and bound to their scope: walking pages returns every item once,
an insert between pages neither repeats nor skips anything, and a cursor that's forged or
belongs to another tenant, user, document or conversation is a 422 problem.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient

from app.providers.llm import FakeLLM
from tests.conftest import Caller

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NewTenant = Callable[[], Awaitable[Caller]]
NewMember = Callable[[Caller], Awaitable[Caller]]


async def _upload(client: AsyncClient, caller: Caller) -> str:
    response = await client.post(
        "/v1/documents",
        headers=caller.headers,
        files={
            "file": (
                f"{uuid.uuid4().hex}.md",
                f"# {uuid.uuid4()}".encode(),
                "text/markdown",
            )
        },
    )
    assert response.status_code in (200, 202), response.text
    return str(response.json()["id"])


async def _walk(
    client: AsyncClient, url: str, caller: Caller, limit: int, key: str = "id"
) -> list[Any]:
    seen: list[Any] = []
    cursor: str | None = None
    for _ in range(50):
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["after"] = cursor
        page = await client.get(url, headers=caller.headers, params=params)
        assert page.status_code == 200, page.text
        body = page.json()
        items = body["items"] if "items" in body else body["messages"]
        assert len(items) <= limit
        seen += [item[key] for item in items]
        cursor = body["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("pagination never ended")


def _assert_bad_cursor(response: Any) -> None:
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Invalid cursor"


# --- documents --------------------------------------------------------------------


async def test_documents_walk_every_page_newest_first_without_repeats(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()  # one seeded document
    uploaded = [await _upload(client, caller) for _ in range(4)]

    ids = await _walk(client, "/v1/documents", caller, limit=2)

    assert len(ids) == 5 and len(set(ids)) == 5
    assert ids[:4] == list(reversed(uploaded))


async def test_a_document_added_between_pages_is_neither_repeated_nor_skipped(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()
    older = [await _upload(client, caller) for _ in range(3)]
    first = (
        await client.get("/v1/documents", headers=caller.headers, params={"limit": 2})
    ).json()
    await _upload(client, caller)  # newer than everything on page 1

    second = (
        await client.get(
            "/v1/documents",
            headers=caller.headers,
            params={"limit": 10, "after": first["next_cursor"]},
        )
    ).json()

    page_one = [d["id"] for d in first["items"]]
    page_two = [d["id"] for d in second["items"]]
    assert page_one == [older[2], older[1]]
    assert page_two[0] == older[0]
    assert not set(page_one) & set(page_two)


async def test_another_tenants_document_cursor_is_rejected(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    tenant_a = await new_tenant()
    tenant_b = await new_tenant()
    await _upload(client, tenant_a)
    cursor = (
        await client.get("/v1/documents", headers=tenant_a.headers, params={"limit": 1})
    ).json()["next_cursor"]
    assert cursor

    _assert_bad_cursor(
        await client.get(
            "/v1/documents", headers=tenant_b.headers, params={"after": cursor}
        )
    )


@pytest.mark.parametrize("after", ["garbage", "a.b", "x" * 600])
async def test_a_malformed_document_cursor_is_rejected(
    client: AsyncClient, new_tenant: NewTenant, after: str
) -> None:
    caller = await new_tenant()

    _assert_bad_cursor(
        await client.get(
            "/v1/documents", headers=caller.headers, params={"after": after}
        )
    )


# --- chunks -----------------------------------------------------------------------


async def test_chunks_walk_in_index_order_and_reject_another_documents_cursor(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    tenant_a = await new_tenant()
    tenant_b = await new_tenant()
    doc_a = (await client.get("/v1/documents", headers=tenant_a.headers)).json()[
        "items"
    ][0]["id"]
    doc_b = (await client.get("/v1/documents", headers=tenant_b.headers)).json()[
        "items"
    ][0]["id"]

    indexes = await _walk(
        client, f"/v1/documents/{doc_a}/chunks", tenant_a, limit=2, key="chunk_index"
    )
    cursor = (
        await client.get(
            f"/v1/documents/{doc_a}/chunks",
            headers=tenant_a.headers,
            params={"limit": 1},
        )
    ).json()["next_cursor"]

    assert indexes == [0, 1, 2]
    _assert_bad_cursor(
        await client.get(
            f"/v1/documents/{doc_b}/chunks",
            headers=tenant_b.headers,
            params={"after": cursor},
        )
    )


# --- conversations and messages ---------------------------------------------------


async def test_conversations_walk_newest_first_and_reject_a_colleagues_cursor(
    client: AsyncClient, new_tenant: NewTenant, new_member: NewMember
) -> None:
    owner = await new_tenant()
    colleague = await new_member(owner)
    created = []
    for n in range(3):
        response = await client.post(
            "/v1/conversations", headers=owner.headers, json={"title": f"c{n}"}
        )
        created.append(response.json()["id"])
    cursor = (
        await client.get(
            "/v1/conversations", headers=owner.headers, params={"limit": 1}
        )
    ).json()["next_cursor"]

    ids = await _walk(client, "/v1/conversations", owner, limit=2)

    assert ids == list(reversed(created))
    _assert_bad_cursor(
        await client.get(
            "/v1/conversations", headers=colleague.headers, params={"after": cursor}
        )
    )


async def test_messages_walk_oldest_first_and_cursors_stay_in_their_conversation(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    caller = await new_tenant()
    first, second = [
        (
            await client.post("/v1/conversations", headers=caller.headers, json={})
        ).json()["id"]
        for _ in range(2)
    ]
    for question in ("How long does charging take?", "And calibration?"):
        await client.post(
            f"/v1/conversations/{first}/messages",
            headers=caller.headers,
            json={"question": question},
        )

    roles = await _walk(
        client, f"/v1/conversations/{first}", caller, limit=3, key="role"
    )
    cursor = (
        await client.get(
            f"/v1/conversations/{first}", headers=caller.headers, params={"limit": 1}
        )
    ).json()["next_cursor"]

    assert roles == ["user", "assistant", "user", "assistant"]
    _assert_bad_cursor(
        await client.get(
            f"/v1/conversations/{second}",
            headers=caller.headers,
            params={"after": cursor},
        )
    )


@pytest.mark.parametrize(
    "path,limit",
    [
        ("/v1/documents", 101),
        ("/v1/conversations", 101),
    ],
)
async def test_limits_are_capped(
    client: AsyncClient, new_tenant: NewTenant, path: str, limit: int
) -> None:
    caller = await new_tenant()

    response = await client.get(path, headers=caller.headers, params={"limit": limit})

    assert response.status_code == 422
