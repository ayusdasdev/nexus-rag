"""OpenAPI polish (M7 7.3): problem+json error responses, explicit operation ids, SSE event
schemas. Error codes per operation follow docs/api-audit.md."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.schemas.chat import (
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    TokenEvent,
)
from app.schemas.problems import Problem

_DESCRIPTIONS = {
    "401": "Missing, invalid or expired bearer token",
    "403": "Authenticated, but not allowed (e.g. debug=true as a non-admin)",
    "404": "Not found, or not yours (indistinguishable)",
    "409": "Conflict (already exists, or a limit is reached)",
    "413": "File too large",
    "415": "Unsupported file type",
    "422": "Invalid input, including any tenant_id field and invalid cursors",
    "429": "Rate limit exceeded; see Retry-After",
    "500": "Internal error (no details exposed); quote the request_id",
    "503": "A dependency (vector store, queue, LLM, rate limiter) is unavailable",
}

# Codes each operation can return beyond the common 401/422/429 (docs/api-audit.md).
_SPECIFIC: dict[str, tuple[str, ...]] = {
    "signup": ("409",),
    "login": ("401",),
    "uploadDocument": ("413", "415", "503"),
    "getDocument": ("404",),
    "deleteDocument": ("404", "503"),
    "listChunks": ("404",),
    "search": ("403", "500", "503"),
    "chat": ("500", "503"),
    "createConversation": ("409",),
    "getConversation": ("404",),
    "deleteConversation": ("404",),
    "postMessage": ("404", "409", "500", "503"),
}

_SSE_EVENTS: list[type[BaseModel]] = [
    SourcesEvent,
    TokenEvent,
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
]


def operation_id(route: APIRoute) -> str:
    """create_conversation -> createConversation."""
    first, *rest = route.name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _problem(code: str) -> dict[str, Any]:
    return {
        "description": _DESCRIPTIONS[code],
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/Problem"}
            }
        },
    }


def _register(schemas: dict[str, Any], model: type[BaseModel]) -> None:
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    for name, sub in schema.pop("$defs", {}).items():
        schemas.setdefault(name, sub)
    schemas[model.__name__] = schema


def install_openapi(app: FastAPI) -> None:
    def build() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        spec = get_openapi(
            title=app.title,
            version=app.version,
            description="Multi-tenant document Q&A. Every error is application/problem+json "
            "with a request_id; lists page by opaque cursors; per-tenant rate limits.",
            routes=app.routes,
        )
        schemas = spec.setdefault("components", {}).setdefault("schemas", {})
        models: list[type[BaseModel]] = [Problem, *_SSE_EVENTS]
        for model in models:
            _register(schemas, model)
        for methods in spec["paths"].values():
            for op in methods.values():
                responses = op["responses"]
                codes = set(_SPECIFIC.get(op["operationId"], ()))
                if op.get("security"):
                    codes |= {"401", "429"}
                if op.get("parameters") or op.get("requestBody"):
                    codes.add("422")
                for code in codes:
                    responses[code] = _problem(code)
        # FastAPI's own 422 schemas are replaced by Problem everywhere.
        schemas.pop("HTTPValidationError", None)
        schemas.pop("ValidationError", None)
        app.openapi_schema = spec
        return spec

    app.openapi = build  # type: ignore[method-assign]
