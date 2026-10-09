"""RFC 9457 problem+json errors and X-Request-ID (M7, api-audit findings 1-2).

Uses the real app factory plus a few test-only routes, so no database is needed.
"""

import logging
import re
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.request_context import current_request_id
from app.main import create_app

PROBLEM = "application/problem+json"


def _app() -> FastAPI:
    app = create_app()

    @app.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    @app.get("/test/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="Thing not found")

    @app.get("/test/needs-int")
    async def needs_int(n: int) -> dict[str, int]:
        return {"n": n}

    @app.get("/test/log")
    async def log() -> dict[str, str | None]:
        logging.getLogger("app.test").warning("inside a request")
        return {"request_id": current_request_id()}

    return app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # raise_app_exceptions=False: see what a real client sees for an unhandled error.
    transport = ASGITransport(app=_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _is_problem(body: dict[str, object], status: int) -> None:
    assert {"type", "title", "status", "detail", "request_id"} <= set(body)
    assert body["status"] == status
    assert body["type"] == "about:blank"


@pytest.mark.asyncio
async def test_an_http_error_is_problem_json_with_the_request_id(
    client: AsyncClient,
) -> None:
    response = await client.get("/test/missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM)
    body = response.json()
    _is_problem(body, 404)
    assert body["title"] == "Not Found"
    assert body["detail"] == "Thing not found"
    assert body["request_id"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_a_validation_error_is_problem_json_listing_the_errors(
    client: AsyncClient,
) -> None:
    response = await client.get("/test/needs-int", params={"n": "seven"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    body = response.json()
    _is_problem(body, 422)
    assert body["detail"] == "Request validation failed"
    assert [e["loc"] for e in body["errors"]] == [["query", "n"]]


@pytest.mark.asyncio
async def test_an_unknown_route_is_problem_json_too(client: AsyncClient) -> None:
    response = await client.get("/nope")

    assert response.status_code == 404
    _is_problem(response.json(), 404)


@pytest.mark.asyncio
async def test_an_auth_failure_keeps_its_www_authenticate_header(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/documents")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    _is_problem(response.json(), 401)


@pytest.mark.asyncio
async def test_an_unhandled_exception_is_a_500_without_a_stack_trace(
    client: AsyncClient,
) -> None:
    response = await client.get("/test/boom", headers={"X-Request-ID": "trace-500"})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.headers["x-request-id"] == "trace-500"
    body = response.json()
    _is_problem(body, 500)
    assert body["request_id"] == "trace-500"
    assert body["detail"] == "Internal server error"
    for leak in ("Traceback", "RuntimeError", "hunter2", "test_problem_details"):
        assert leak not in response.text


@pytest.mark.asyncio
async def test_an_incoming_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc-123.def_4"})

    assert response.headers["x-request-id"] == "abc-123.def_4"


@pytest.mark.asyncio
async def test_a_missing_request_id_is_generated(client: AsyncClient) -> None:
    first = await client.get("/health")
    second = await client.get("/health")

    assert re.fullmatch(r"[0-9a-f]{32}", first.headers["x-request-id"])
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe",
    ["has space", "x" * 129, "line\nbreak", "<script>", "été", ""],
)
async def test_an_unsafe_request_id_is_replaced_not_echoed(
    client: AsyncClient, unsafe: str
) -> None:
    response = await client.get(
        "/health", headers={b"X-Request-ID": unsafe.encode("utf-8")}
    )

    assert response.headers["x-request-id"] != unsafe
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


@pytest.mark.asyncio
async def test_log_lines_carry_the_request_id(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="app.test"):
        response = await client.get("/test/log", headers={"X-Request-ID": "log-me"})

    assert response.json() == {"request_id": "log-me"}
    record = next(r for r in caplog.records if r.getMessage() == "inside a request")
    assert record.request_id == "log-me"  # type: ignore[attr-defined]


def test_outside_a_request_there_is_no_request_id() -> None:
    assert current_request_id() is None
    assert logging.makeLogRecord({}).__dict__.get("request_id", None) in (None, "-")
