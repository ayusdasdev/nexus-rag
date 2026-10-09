"""Per-tenant and per-user rate limits on the real API with real Redis (M7).

Your limits: chat 5 burst then 1/min per tenant, search 20 then 1/5 s, everything else 120
then 2/s; each user gets half. Keys come only from the verified token, never from IP
headers. Fail closed on chat, open elsewhere, when Redis is down.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from redis.asyncio import Redis

from app.api.rate_limit import get_rate_limit_store
from app.core.config import Settings, get_settings
from app.main import app
from app.providers.llm import FakeLLM
from app.repositories.rate_limit_store import RedisRateLimitStore
from tests.conftest import Caller

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.real_rate_limit,
]

NewTenant = Callable[[], Awaitable[Caller]]
NewMember = Callable[[Caller], Awaitable[Caller]]
QUESTION = {"question": "How long does charging take?"}


@pytest_asyncio.fixture(loop_scope="session")
async def real_store() -> AsyncIterator[None]:
    client = Redis.from_url(get_settings().redis_url)
    app.dependency_overrides[get_rate_limit_store] = lambda: RedisRateLimitStore(client)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_rate_limit_store, None)
        await client.aclose()


def _settings(**values: Any) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(**values)


def _assert_429(response: Response, retry_after: str, limit: str) -> None:
    assert response.status_code == 429, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Rate limit exceeded"
    assert response.headers["retry-after"] == retry_after
    assert response.headers["x-ratelimit-limit"] == limit
    assert response.headers["x-ratelimit-remaining"] == "0"


async def _chat(client: AsyncClient, caller: Caller, **headers: str) -> Response:
    return await client.post(
        "/v1/chat", headers={**caller.headers, **headers}, json=QUESTION
    )


async def test_a_users_chat_burst_is_capped_and_the_llm_is_not_called_after(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM, real_store: None
) -> None:
    caller = await new_tenant()

    statuses = [(await _chat(client, caller)).status_code for _ in range(2)]
    third = await _chat(client, caller)

    assert statuses == [200, 200]
    # The user bucket (2.5 burst, 1 per 120 s) is short by half a token: 60 s.
    _assert_429(third, retry_after="60", limit="5")
    assert len(fake_llm.calls) == 2


async def test_users_share_their_tenants_chat_budget(
    client: AsyncClient,
    new_tenant: NewTenant,
    new_member: NewMember,
    fake_llm: FakeLLM,
    real_store: None,
) -> None:
    owner = await new_tenant()
    first, second = await new_member(owner), await new_member(owner)

    owner_runs = [(await _chat(client, owner)).status_code for _ in range(2)]
    first_runs = [(await _chat(client, first)).status_code for _ in range(2)]
    second_ok = await _chat(client, second)
    second_denied = await _chat(client, second)

    assert owner_runs == first_runs == [200, 200]
    assert second_ok.status_code == 200
    # Tenant bucket (5) is now empty even though this user's own bucket isn't.
    _assert_429(second_denied, retry_after="60", limit="5")


async def test_tenants_have_separate_buckets(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM, real_store: None
) -> None:
    tenant_a, tenant_b = await new_tenant(), await new_tenant()
    for _ in range(3):
        await _chat(client, tenant_a)

    assert (await _chat(client, tenant_b)).status_code == 200


@pytest.mark.parametrize(
    "spoof",
    [
        {"X-Forwarded-For": "203.0.113.7"},
        {"X-Real-IP": "198.51.100.9"},
        {"X-Tenant-Id": "00000000-0000-0000-0000-000000000000"},
        {"X-Request-ID": "fresh-bucket-please"},
    ],
)
async def test_spoofed_headers_never_move_a_caller_to_a_fresh_bucket(
    client: AsyncClient,
    new_tenant: NewTenant,
    fake_llm: FakeLLM,
    real_store: None,
    spoof: dict[str, str],
) -> None:
    caller = await new_tenant()
    for _ in range(2):
        await _chat(client, caller)

    assert (await _chat(client, caller, **spoof)).status_code == 429


async def test_unauthenticated_requests_are_401_and_spend_nothing(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM, real_store: None
) -> None:
    caller = await new_tenant()
    for _ in range(5):
        assert (await client.post("/v1/chat", json=QUESTION)).status_code == 401

    assert [(await _chat(client, caller)).status_code for _ in range(2)] == [200, 200]


async def test_search_has_its_own_limit(
    client: AsyncClient, new_tenant: NewTenant, real_store: None
) -> None:
    caller = await new_tenant()
    _settings(rate_limit_search_capacity=2, rate_limit_search_refill_per_second=0.01)
    try:
        first = await client.post(
            "/v1/search", headers=caller.headers, json={"query": "x"}
        )
        second = await client.post(
            "/v1/search", headers=caller.headers, json={"query": "x"}
        )
        listing = await client.get("/v1/documents", headers=caller.headers)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert first.status_code == 200
    # User bucket: 1 burst, 0.005/s, so 200 s for the next token.
    _assert_429(second, retry_after="200", limit="2")
    assert listing.status_code == 200  # the default class is a different bucket


async def test_other_routes_use_the_default_limit(
    client: AsyncClient, new_tenant: NewTenant, real_store: None
) -> None:
    caller = await new_tenant()
    _settings(rate_limit_default_capacity=2, rate_limit_default_refill_per_second=0.5)
    try:
        first = await client.get("/v1/conversations", headers=caller.headers)
        second = await client.get("/v1/documents", headers=caller.headers)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert first.status_code == 200
    _assert_429(second, retry_after="4", limit="2")


async def test_with_redis_down_chat_fails_closed_and_reads_fail_open(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM
) -> None:
    caller = await new_tenant()
    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)
    app.dependency_overrides[get_rate_limit_store] = lambda: RedisRateLimitStore(dead)
    try:
        chat = await _chat(client, caller)
        listing = await client.get("/v1/documents", headers=caller.headers)
    finally:
        app.dependency_overrides.pop(get_rate_limit_store, None)
        await dead.aclose()

    assert chat.status_code == 503
    assert chat.headers["content-type"].startswith("application/problem+json")
    assert fake_llm.calls == []
    assert listing.status_code == 200


async def test_rate_limiting_can_be_switched_off(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM, real_store: None
) -> None:
    caller = await new_tenant()
    _settings(rate_limit_enabled=False)
    try:
        statuses = [(await _chat(client, caller)).status_code for _ in range(4)]
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert statuses == [200, 200, 200, 200]


async def test_conversation_messages_share_the_chat_bucket(
    client: AsyncClient, new_tenant: NewTenant, fake_llm: FakeLLM, real_store: None
) -> None:
    caller = await new_tenant()
    conversation = (
        await client.post("/v1/conversations", headers=caller.headers, json={})
    ).json()["id"]
    await _chat(client, caller)
    await _chat(client, caller)

    response = await client.post(
        f"/v1/conversations/{conversation}/messages",
        headers=caller.headers,
        json=QUESTION,
    )

    assert response.status_code == 429
    assert uuid.UUID(conversation)
