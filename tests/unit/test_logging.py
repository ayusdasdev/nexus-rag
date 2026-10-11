"""JSON structured logs with request_id and tenant_id from context (M9 9.1)."""

import io
import json
import logging
import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.logging import JsonFormatter
from app.core.request_context import (
    current_tenant_id,
    reset_tenant_id,
    set_request_id,
    set_tenant_id,
)
from app.main import create_app


@pytest.fixture
def captured() -> Iterator[io.StringIO]:
    """A JSON handler on the root logger, like production, captured into a buffer."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    old_level = root.level
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_a_log_line_is_one_json_object_with_the_standard_fields(
    captured: io.StringIO,
) -> None:
    logging.getLogger("app.test").info("two\nlines %s", "here")

    (line,) = _lines(captured)
    assert line["level"] == "INFO"
    assert line["logger"] == "app.test"
    assert line["message"] == "two\nlines here"
    assert line["request_id"] is None and line["tenant_id"] is None
    assert isinstance(line["ts"], str) and line["ts"].endswith("Z")


def test_request_and_tenant_ids_come_from_the_context(captured: io.StringIO) -> None:
    tenant = uuid.uuid4()
    request_token = set_request_id("req-1")
    tenant_token = set_tenant_id(tenant)
    try:
        logging.getLogger("app.test").info("inside")
    finally:
        reset_tenant_id(tenant_token)
        set_request_id(None)
    del request_token

    (line,) = _lines(captured)
    assert (line["request_id"], line["tenant_id"]) == ("req-1", str(tenant))
    assert current_tenant_id() is None


def test_stage_and_ms_given_as_extra_are_kept(captured: io.StringIO) -> None:
    logging.getLogger("app.test").info("done", extra={"stage": "rerank", "ms": 12.5})

    (line,) = _lines(captured)
    assert (line["stage"], line["ms"]) == ("rerank", 12.5)


def test_an_exception_is_logged_by_type_and_frames_never_its_message(
    captured: io.StringIO,
) -> None:
    try:
        raise RuntimeError("database password is hunter2")
    except RuntimeError:
        logging.getLogger("app.test").exception("failed")

    (line,) = _lines(captured)
    assert line["exc_type"] == "RuntimeError"
    assert "test_logging.py" in str(line["stack"])
    assert "hunter2" not in captured.getvalue()


def _app_with_log_route() -> FastAPI:
    app = create_app()

    @app.get("/test/log")
    async def log() -> dict[str, str]:
        logging.getLogger("app.test").warning("inside a request")
        return {}

    @app.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    return app


@pytest.mark.asyncio
async def test_a_request_logs_its_request_id_and_resets_the_tenant(
    captured: io.StringIO,
) -> None:
    transport = ASGITransport(app=_app_with_log_route(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test/log", headers={"X-Request-ID": "abc-123"})
        boom = await client.get("/test/boom")

    lines = _lines(captured)
    inside = next(x for x in lines if x["message"] == "inside a request")
    assert inside["request_id"] == "abc-123" == response.headers["x-request-id"]
    assert boom.status_code == 500
    assert "hunter2" not in captured.getvalue()
    assert current_tenant_id() is None


@pytest.mark.asyncio
async def test_verifying_a_token_puts_its_tenant_into_the_log_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api import deps
    from app.core.security import TokenPayload

    tenant, user = uuid.uuid4(), uuid.uuid4()

    class Row:
        id = user
        tenant_id = tenant
        email = "a@example.com"
        role = "admin"
        created_at = None

    async def get_user(t: uuid.UUID, u: uuid.UUID) -> Row:
        return Row()

    monkeypatch.setattr(
        deps,
        "decode_access_token",
        lambda _t: TokenPayload(user_id=user, tenant_id=tenant, role="admin"),
    )
    monkeypatch.setattr(deps, "get_user_by_id", get_user)
    token = set_tenant_id(None)
    try:
        await deps.get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
        )
        assert current_tenant_id() == tenant
    finally:
        reset_tenant_id(token)


@pytest.mark.asyncio
async def test_each_request_gets_its_own_trace_under_its_request_id() -> None:
    from app.core import tracing

    app = create_app()
    seen: list[tuple[str | None, int]] = []

    @app.get("/test/trace")
    async def trace_route() -> dict[str, str]:
        trace = tracing.current_trace()
        assert trace is not None
        tracing.record("stage", 1.0)
        seen.append((trace.request_id, len(trace.spans)))
        return {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/test/trace", headers={"X-Request-ID": "r-1"})
        await client.get("/test/trace", headers={"X-Request-ID": "r-2"})

    assert seen == [("r-1", 1), ("r-2", 1)]
    assert tracing.current_trace() is None
