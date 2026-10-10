"""Rate limits on signup and login (M7 review, HIGH-1), real Redis.

Your decisions: per client IP (socket peer; X-Forwarded-For only from TRUSTED_PROXIES),
plus a per-email login bucket and a global signup budget; fail closed when Redis is down.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from redis.asyncio import Redis

from app.api.rate_limit import get_rate_limit_store
from app.core.config import Settings, get_settings
from app.main import app
from app.repositories.rate_limit_store import RedisRateLimitStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.real_rate_limit,
]


@pytest_asyncio.fixture(loop_scope="session")
async def real_store() -> AsyncIterator[None]:
    client = Redis.from_url(get_settings().redis_url)
    # Each test gets fresh buckets: the test client's peer is always 127.0.0.1.
    await client.delete(*[k async for k in client.scan_iter("rl:signup:*")] or ["-"])
    await client.delete(*[k async for k in client.scan_iter("rl:login:*")] or ["-"])
    app.dependency_overrides[get_rate_limit_store] = lambda: RedisRateLimitStore(client)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_rate_limit_store, None)
        await client.aclose()


def _settings(**values: Any) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(**values)


@pytest.fixture(autouse=True)
def _reset_settings() -> Any:
    yield
    app.dependency_overrides.pop(get_settings, None)


async def _signup(client: AsyncClient, **headers: str) -> Response:
    return await client.post(
        "/v1/auth/signup",
        headers=headers,
        json={
            "tenant_name": "t",
            "email": f"rl-{uuid.uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )


async def _login(client: AsyncClient, email: str, **headers: str) -> Response:
    return await client.post(
        "/v1/auth/login",
        headers=headers,
        json={"email": email, "password": "wrong-password"},
    )


def _assert_429(response: Response) -> None:
    assert response.status_code == 429, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert int(response.headers["retry-after"]) > 0


async def test_login_guessing_one_email_is_cut_off_after_five_tries(
    client: AsyncClient, real_store: None
) -> None:
    email = f"victim-{uuid.uuid4().hex}@example.com"

    statuses = [(await _login(client, email)).status_code for _ in range(5)]
    sixth = await _login(client, email)
    other = await _login(client, f"other-{uuid.uuid4().hex}@example.com")

    assert statuses == [401] * 5
    _assert_429(sixth)
    # 1 per minute, minus the refill accrued during five bcrypt checks (~0.25 s each).
    assert 55 <= int(sixth.headers["retry-after"]) <= 60
    assert other.status_code == 401  # another email from the same IP still has room


async def test_login_from_one_ip_is_capped_across_emails(
    client: AsyncClient, real_store: None
) -> None:
    _settings(
        rate_limit_login_ip_capacity=3, rate_limit_login_ip_refill_per_second=0.01
    )

    statuses = [
        (await _login(client, f"a-{uuid.uuid4().hex}@example.com")).status_code
        for _ in range(3)
    ]
    fourth = await _login(client, f"a-{uuid.uuid4().hex}@example.com")

    assert statuses == [401] * 3
    _assert_429(fourth)


async def test_signup_is_capped_per_ip_and_spoofed_forwarding_is_ignored(
    client: AsyncClient, real_store: None
) -> None:
    statuses = [
        (await _signup(client, **{"X-Forwarded-For": f"198.51.100.{n}"})).status_code
        for n in range(3)
    ]
    fourth = await _signup(client, **{"X-Forwarded-For": "198.51.100.99"})

    assert statuses == [201] * 3
    _assert_429(fourth)


async def test_a_trusted_proxy_gives_each_real_client_its_own_bucket(
    client: AsyncClient, real_store: None
) -> None:
    _settings(trusted_proxies=["127.0.0.1/32"])

    statuses = [
        (await _signup(client, **{"X-Forwarded-For": f"198.51.100.{n}"})).status_code
        for n in range(5)
    ]

    assert statuses == [201] * 5


async def test_the_global_signup_budget_caps_many_clients(
    client: AsyncClient, real_store: None
) -> None:
    _settings(
        trusted_proxies=["127.0.0.1/32"],
        rate_limit_signup_global_capacity=2,
        rate_limit_signup_global_refill_per_second=0.001,
    )

    statuses = [
        (await _signup(client, **{"X-Forwarded-For": f"203.0.113.{n}"})).status_code
        for n in range(3)
    ]

    assert statuses[:2] == [201, 201]
    assert statuses[2] == 429


async def test_a_rejected_body_spends_nothing(
    client: AsyncClient, real_store: None
) -> None:
    for _ in range(5):
        bad = await client.post("/v1/auth/signup", json={"email": "x"})
        assert bad.status_code == 422

    assert (await _signup(client)).status_code == 201


@pytest.mark.parametrize("path", ["/v1/auth/signup", "/v1/auth/login"])
async def test_with_redis_down_signup_and_login_fail_closed(
    client: AsyncClient, path: str
) -> None:
    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)
    app.dependency_overrides[get_rate_limit_store] = lambda: RedisRateLimitStore(dead)
    try:
        body = {
            "email": f"d-{uuid.uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        }
        if path.endswith("signup"):
            body["tenant_name"] = "t"
        response = await client.post(path, json=body)
    finally:
        app.dependency_overrides.pop(get_rate_limit_store, None)
        await dead.aclose()

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
