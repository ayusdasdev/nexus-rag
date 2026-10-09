"""Every 4xx/5xx from the real API is problem+json carrying its request id (M7 7.2)."""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient, Response

from app.core.config import Settings, get_settings
from app.main import app
from tests.conftest import Caller

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

NewTenant = Callable[[], Awaitable[Caller]]
NewMember = Callable[[Caller], Awaitable[Caller]]


def _assert_problem(response: Response, status: int) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == status
    assert body["type"] == "about:blank"
    assert isinstance(body["title"], str) and body["title"]
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["request_id"] == response.headers["x-request-id"]


async def test_401_without_a_token(client: AsyncClient) -> None:
    _assert_problem(await client.get("/v1/documents"), 401)


async def test_401_with_a_bad_token(client: AsyncClient) -> None:
    response = await client.get(
        "/v1/conversations", headers={"Authorization": "Bearer not-a-jwt"}
    )
    _assert_problem(response, 401)


async def test_403_for_a_member_asking_for_debug(
    client: AsyncClient, new_tenant: NewTenant, new_member: NewMember
) -> None:
    member = await new_member(await new_tenant())
    response = await client.post(
        "/v1/search", headers=member.headers, json={"query": "x", "debug": True}
    )
    _assert_problem(response, 403)


async def test_404_for_a_missing_document_and_conversation(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()
    for path in (f"/v1/documents/{uuid.uuid4()}", f"/v1/conversations/{uuid.uuid4()}"):
        _assert_problem(await client.get(path, headers=caller.headers), 404)


async def test_409_for_a_duplicate_signup(client: AsyncClient) -> None:
    body = {
        "tenant_name": "t",
        "email": f"dup-{uuid.uuid4().hex}@example.com",
        "password": "correct-horse-battery",
    }
    assert (await client.post("/v1/auth/signup", json=body)).status_code == 201
    _assert_problem(await client.post("/v1/auth/signup", json=body), 409)


async def test_415_and_422_for_bad_uploads(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()
    exe = await client.post(
        "/v1/documents",
        headers=caller.headers,
        files={"file": ("x.exe", b"MZ\x90\x00binary", "application/octet-stream")},
    )
    empty = await client.post(
        "/v1/documents",
        headers=caller.headers,
        files={"file": ("e.md", b"", "text/markdown")},
    )
    _assert_problem(exe, 415)
    _assert_problem(empty, 422)


async def test_422_for_an_invalid_body_lists_errors_without_echoing_input(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()
    response = await client.post(
        "/v1/chat",
        headers=caller.headers,
        json={"question": "x", "tenant_id": "SECRET-INPUT-VALUE"},
    )
    _assert_problem(response, 422)
    assert response.json()["errors"]
    assert "SECRET-INPUT-VALUE" not in response.text


async def test_503_when_no_llm_is_configured(
    client: AsyncClient, new_tenant: NewTenant
) -> None:
    caller = await new_tenant()
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct(
        **{
            **Settings().model_dump(),
            "llm_provider": "anthropic",
            "anthropic_api_key": None,
        }
    )
    try:
        response = await client.post(
            "/v1/chat", headers=caller.headers, json={"question": "How long?"}
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
    _assert_problem(response, 503)
