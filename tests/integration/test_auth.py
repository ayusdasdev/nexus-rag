import asyncio
import base64
import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.core import security
from app.core.security import create_access_token

# All tests here share one event loop: the SQLAlchemy engine in
# app/repositories/session.py is created once at import time and its
# connection pool binds to whichever loop first uses it - the default
# per-test loop scope would otherwise hand later tests a closed/foreign loop.
pytestmark = pytest.mark.asyncio(loop_scope="module")


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex}@example.com"


def _unique_tenant_name() -> str:
    return f"tenant-{uuid.uuid4().hex}"


def _tamper_payload(token: str) -> str:
    """Flip a claim in the payload segment without re-signing - signature must then fail."""
    header_b64, payload_b64, signature_b64 = token.split(".")
    padding = "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    payload["role"] = "admin-tampered"
    new_payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
        .decode("utf-8")
        .rstrip("=")
    )
    return f"{header_b64}.{new_payload_b64}.{signature_b64}"


async def _signup(client: AsyncClient, email: str | None = None) -> dict[str, Any]:
    response = await client.post(
        "/auth/signup",
        json={
            "tenant_name": _unique_tenant_name(),
            "email": email or _unique_email(),
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_signup_creates_tenant_and_user_and_returns_token(
    client: AsyncClient,
) -> None:
    email = _unique_email()
    response = await client.post(
        "/auth/signup",
        json={
            "tenant_name": _unique_tenant_name(),
            "email": email,
            "password": "correct-horse-battery",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "admin"
    assert "tenant_id" in body["user"]


async def test_signup_duplicate_email_returns_409(client: AsyncClient) -> None:
    email = _unique_email()
    await _signup(client, email=email)

    second = await client.post(
        "/auth/signup",
        json={
            "tenant_name": _unique_tenant_name(),
            "email": email,
            "password": "another-password",
        },
    )

    assert second.status_code == 409


async def test_login_wrong_password_returns_401_with_generic_message(
    client: AsyncClient,
) -> None:
    signup_body = await _signup(client)
    email = signup_body["user"]["email"]

    response = await client.post(
        "/auth/login", json={"email": email, "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


async def test_me_with_valid_token_returns_tenant_id(client: AsyncClient) -> None:
    signup_body = await _signup(client)
    token = signup_body["access_token"]
    tenant_id = signup_body["user"]["tenant_id"]

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == tenant_id


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_with_tampered_token_returns_401(client: AsyncClient) -> None:
    signup_body = await _signup(client)
    tampered = _tamper_payload(signup_body["access_token"])

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tampered}"}
    )

    assert response.status_code == 401


async def test_me_with_expired_token_returns_401(client: AsyncClient) -> None:
    signup_body = await _signup(client)
    user = signup_body["user"]
    expired_token = create_access_token(
        uuid.UUID(user["id"]),
        uuid.UUID(user["tenant_id"]),
        user["role"],
        expires_delta=timedelta(seconds=-10),
    )

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert response.status_code == 401


async def test_signup_concurrent_duplicate_email_only_one_succeeds(
    client: AsyncClient,
) -> None:
    """Regression test for the TOCTOU race: the service's pre-check alone
    cannot stop two concurrent signups with the same email from both
    succeeding, since each creates a brand-new tenant. The DB's global
    unique constraint on users.email is the real backstop."""
    email = _unique_email()

    async def attempt() -> int:
        response = await client.post(
            "/auth/signup",
            json={
                "tenant_name": _unique_tenant_name(),
                "email": email,
                "password": "correct-horse-battery",
            },
        )
        return response.status_code

    statuses = await asyncio.gather(attempt(), attempt())

    assert sorted(statuses) == [201, 409]


async def test_login_runs_password_verification_even_for_unknown_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for the timing side-channel: verify_password must run
    (against the fixed dummy hash) even when no user matches the email, so
    an unknown-email response isn't measurably faster than a wrong-password
    one."""
    calls: list[str] = []
    original_verify = security.verify_password

    def spy_verify(plain: str, hashed: str) -> bool:
        calls.append(hashed)
        return original_verify(plain, hashed)

    monkeypatch.setattr(security, "verify_password", spy_verify)

    response = await client.post(
        "/auth/login", json={"email": _unique_email(), "password": "whatever"}
    )

    assert response.status_code == 401
    assert calls == [security.DUMMY_HASH]


# GET /v1/auth/me - same handler/schema as GET /auth/me, mounted under a
# versioned path. No request body, so "validation error" is adapted to a
# malformed (non-JWT) bearer token, the closest analog for a header-only GET.


async def test_v1_me_with_valid_token_returns_tenant_id(client: AsyncClient) -> None:
    signup_body = await _signup(client)
    token = signup_body["access_token"]
    tenant_id = signup_body["user"]["tenant_id"]

    response = await client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == tenant_id


async def test_v1_me_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/v1/auth/me")

    assert response.status_code == 401


async def test_v1_me_with_malformed_token_returns_401(client: AsyncClient) -> None:
    response = await client.get(
        "/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt-at-all"}
    )

    assert response.status_code == 401
