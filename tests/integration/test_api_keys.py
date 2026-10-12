"""Read-only, tenant-bound API keys (M9 9.2, your choice for the MCP server).

Admins create, list and revoke them. A key reaches only an allowlist of read routes in its
own tenant; everything else is 403, and a revoked or unknown key is 401.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import Caller

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NewTenant = Callable[[], Awaitable[Caller]]
NewMember = Callable[[Caller], Awaitable[Caller]]
KEYS = "/v1/api-keys"


async def _key(client: AsyncClient, admin: Caller, name: str = "mcp") -> dict[str, Any]:
    response = await client.post(KEYS, headers=admin.headers, json={"name": name})
    assert response.status_code == 201, response.text
    return dict(response.json())


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# --- managing keys ----------------------------------------------------------------------


async def test_an_admin_creates_a_key_that_is_shown_once_and_listed_without_it(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    admin = await new_tenant()

    created = await _key(client, admin, "claude code")
    listed = (await client.get(KEYS, headers=admin.headers)).json()

    assert created["key"].startswith("nxk_")
    assert created["prefix"] == created["key"][:12]
    assert (created["name"], created["scope"]) == ("claude code", "read")
    (item,) = listed["items"]
    assert item["id"] == created["id"] and item["prefix"] == created["prefix"]
    assert "key" not in item and "key_hash" not in item
    assert created["key"] not in str(listed)


async def test_a_member_cannot_create_list_or_revoke_keys(
    client: AsyncClient, new_tenant: NewTenant, new_member: NewMember
) -> None:
    admin = await new_tenant()
    member = await new_member(admin)
    key = await _key(client, admin)

    create = await client.post(KEYS, headers=member.headers, json={"name": "x"})
    listing = await client.get(KEYS, headers=member.headers)
    revoke = await client.delete(f"{KEYS}/{key['id']}", headers=member.headers)

    assert create.status_code == listing.status_code == revoke.status_code == 403


@pytest.mark.parametrize(
    "body", [{}, {"name": ""}, {"name": "x" * 101}, {"name": "x", "tenant_id": "y"}]
)
async def test_an_invalid_key_request_is_422(
    client: AsyncClient, new_tenant: NewTenant, body: dict[str, object]
) -> None:
    admin = await new_tenant()

    response = await client.post(KEYS, headers=admin.headers, json=body)

    assert response.status_code == 422


async def test_managing_keys_without_a_token_is_401(client: AsyncClient) -> None:
    assert (await client.post(KEYS, json={"name": "x"})).status_code == 401
    assert (await client.get(KEYS)).status_code == 401


async def test_another_tenants_admin_cannot_revoke_my_key(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    admin = await new_tenant()
    other = await new_tenant()
    key = await _key(client, admin)

    response = await client.delete(f"{KEYS}/{key['id']}", headers=other.headers)
    still_works = await client.get("/v1/documents", headers=_bearer(key["key"]))

    assert response.status_code == 404
    assert still_works.status_code == 200


# --- what a key can do ------------------------------------------------------------------


async def test_a_key_searches_and_lists_only_its_own_tenants_documents(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    admin = await new_tenant()
    other = await new_tenant()
    key = await _key(client, admin)

    search = await client.post(
        "/v1/search",
        headers=_bearer(key["key"]),
        json={"query": "How long does charging take?"},
    )
    documents = await client.get("/v1/documents", headers=_bearer(key["key"]))

    assert search.status_code == 200, search.text
    returned = {r["chunk_id"] for r in search.json()["items"]}
    assert returned and returned <= set(admin.chunk_ids)
    assert not returned & set(other.chunk_ids)
    assert documents.status_code == 200
    document_id = documents.json()["items"][0]["id"]
    one = await client.get(f"/v1/documents/{document_id}", headers=_bearer(key["key"]))
    chunks = await client.get(
        f"/v1/documents/{document_id}/chunks", headers=_bearer(key["key"])
    )
    assert one.status_code == chunks.status_code == 200


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/v1/chat", {"question": "q"}),
        ("post", "/v1/conversations", {"title": None}),
        ("get", "/v1/conversations", None),
        ("delete", "/v1/documents/{doc}", None),
        ("get", "/v1/traces/abc", None),
        ("post", KEYS, {"name": "minted by a key"}),
        ("get", KEYS, None),
        ("get", "/v1/auth/me", None),
    ],
)
async def test_a_key_is_refused_everywhere_outside_the_read_allowlist(
    client: AsyncClient,
    new_tenant: NewTenant,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    admin = await new_tenant()
    key = await _key(client, admin)
    documents = await client.get("/v1/documents", headers=admin.headers)
    path = path.format(doc=documents.json()["items"][0]["id"])

    kwargs: dict[str, Any] = {"headers": _bearer(key["key"])}
    if body is not None:
        kwargs["json"] = body
    response = await client.request(method.upper(), path, **kwargs)

    assert response.status_code == 403, (path, response.text)
    # Nothing was deleted on the way.
    assert (await client.get("/v1/documents", headers=admin.headers)).json()["items"]


async def test_a_key_made_by_an_admin_still_cannot_use_admin_only_search_debug(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    admin = await new_tenant()
    key = await _key(client, admin)

    response = await client.post(
        "/v1/search", headers=_bearer(key["key"]), json={"query": "q", "debug": True}
    )

    assert response.status_code == 403


async def test_uploading_with_a_key_is_refused(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    admin = await new_tenant()
    key = await _key(client, admin)

    response = await client.post(
        "/v1/documents",
        headers=_bearer(key["key"]),
        files={"file": ("x.md", b"# x\n\nhello", "text/markdown")},
    )

    assert response.status_code == 403


async def test_a_revoked_or_unknown_key_is_401(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    admin = await new_tenant()
    key = await _key(client, admin)

    revoke = await client.delete(f"{KEYS}/{key['id']}", headers=admin.headers)
    revoked = await client.get("/v1/documents", headers=_bearer(key["key"]))
    unknown = await client.get("/v1/documents", headers=_bearer("nxk_" + "A" * 43))

    assert revoke.status_code == 204
    assert revoked.status_code == unknown.status_code == 401
    assert (await client.get(KEYS, headers=admin.headers)).json()["items"] == []


async def test_revoking_an_unknown_key_is_404(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    admin = await new_tenant()

    response = await client.delete(f"{KEYS}/{uuid.uuid4()}", headers=admin.headers)

    assert response.status_code == 404
