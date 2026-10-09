"""One error shape everywhere: RFC 9457 problem+json with the request id (M7)."""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


def problem_body(status: int, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "request_id": current_request_id(),
        **extra,
    }


def problem_response(
    status: int, detail: str, headers: Mapping[str, str] | None = None, **extra: Any
) -> JSONResponse:
    return JSONResponse(
        problem_body(status, detail, **extra),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = (
        exc.detail
        if isinstance(exc.detail, str)
        else HTTPStatus(exc.status_code).phrase
    )
    return problem_response(exc.status_code, detail, headers=exc.headers)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # The submitted values ("input") are left out: they can be document text or secrets.
    errors = [
        {
            "loc": list(e.get("loc", ())),
            "msg": e.get("msg", ""),
            "type": e.get("type", ""),
        }
        for e in exc.errors()
    ]
    return problem_response(422, "Request validation failed", errors=errors)


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
