"""OpenAPI quality (M7 7.3, api-audit findings 5-7 and 9)."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.main import create_app

SPEC: dict[str, Any] = create_app().openapi()
OPERATIONS = [
    (path, method, op)
    for path, methods in SPEC["paths"].items()
    for method, op in methods.items()
]
PROBLEM_REF = "#/components/schemas/Problem"


def _problem_codes(op: dict[str, Any]) -> set[str]:
    codes = set()
    for code, response in op["responses"].items():
        content = response.get("content", {})
        if (
            content.get("application/problem+json", {}).get("schema", {}).get("$ref")
            == PROBLEM_REF
        ):
            codes.add(code)
    return codes


def _op(method: str, path: str) -> dict[str, Any]:
    return dict(SPEC["paths"][path][method])


def test_operation_ids_are_explicit_camel_case_and_unique() -> None:
    ids = [op["operationId"] for _, _, op in OPERATIONS]

    assert len(ids) == len(set(ids))
    for operation_id in ids:
        assert re.fullmatch(r"[a-z][a-zA-Z]+", operation_id), operation_id
    assert _op("post", "/v1/documents")["operationId"] == "uploadDocument"


def test_the_unversioned_auth_duplicates_are_not_in_the_schema() -> None:
    assert not [path for path in SPEC["paths"] if path.startswith("/auth/")]
    assert "/v1/auth/login" in SPEC["paths"]


def test_every_error_response_is_a_problem() -> None:
    for path, method, op in OPERATIONS:
        for code, response in op["responses"].items():
            if (path, code) == ("/ready", "503"):
                continue  # the readiness report itself, documented with its own schema
            if code.startswith(("4", "5")):
                assert code in _problem_codes(op), f"{method} {path} {code}: {response}"


def test_every_secured_operation_documents_401_and_429() -> None:
    for path, method, op in OPERATIONS:
        if op.get("security"):
            assert {"401", "429"} <= _problem_codes(op), f"{method} {path}"


def test_every_operation_with_input_documents_422() -> None:
    for path, method, op in OPERATIONS:
        if op.get("parameters") or op.get("requestBody"):
            assert "422" in _problem_codes(op), f"{method} {path}"


@pytest.mark.parametrize(
    "method,path,codes",
    [
        ("post", "/v1/auth/signup", {"409"}),
        ("post", "/v1/auth/login", {"401"}),
        ("post", "/v1/documents", {"413", "415", "503"}),
        ("get", "/v1/documents/{document_id}", {"404"}),
        ("delete", "/v1/documents/{document_id}", {"404", "503"}),
        ("get", "/v1/documents/{document_id}/chunks", {"404"}),
        ("post", "/v1/search", {"403", "500", "503"}),
        ("post", "/v1/chat", {"500", "503"}),
        ("post", "/v1/conversations", {"409"}),
        ("get", "/v1/conversations/{conversation_id}", {"404"}),
        ("delete", "/v1/conversations/{conversation_id}", {"404"}),
        ("post", "/v1/conversations/{conversation_id}/messages", {"404", "409", "503"}),
    ],
)
def test_route_specific_errors_are_documented(
    method: str, path: str, codes: set[str]
) -> None:
    assert codes <= _problem_codes(_op(method, path))


def test_ready_documents_its_503_with_the_readiness_report() -> None:
    response = _op("get", "/ready")["responses"]["503"]

    assert response["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ReadyResponse"
    )


def test_sse_event_payloads_and_the_problem_are_reusable_schemas() -> None:
    schemas = SPEC["components"]["schemas"]

    for name in (
        "Problem",
        "SourcesEvent",
        "TokenEvent",
        "CitationsEvent",
        "DoneEvent",
        "ErrorEvent",
    ):
        assert name in schemas, name
    assert {"type", "title", "status", "detail", "request_id"} <= set(
        schemas["Problem"]["properties"]
    )


def test_every_operation_has_a_summary_description_and_tag() -> None:
    for path, method, op in OPERATIONS:
        assert op.get("summary"), f"{method} {path}"
        assert op.get("description"), f"{method} {path}"
        assert op.get("tags"), f"{method} {path}"


def test_every_json_request_body_has_an_example() -> None:
    schemas = SPEC["components"]["schemas"]
    for path, method, op in OPERATIONS:
        body = op.get("requestBody", {}).get("content", {}).get("application/json")
        if body:
            name = body["schema"]["$ref"].rsplit("/", 1)[-1]
            assert "example" in schemas[name] or "examples" in schemas[name], (
                f"{method} {path}"
            )


def test_the_exported_openapi_json_is_current() -> None:
    exported = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"

    assert json.loads(exported.read_text(encoding="utf-8")) == SPEC, (
        "docs/openapi.json is stale: run `make openapi`"
    )


def test_every_ref_in_the_spec_resolves() -> None:
    # Importers such as Postman choke on dangling references.
    schemas = SPEC["components"]["schemas"]
    refs: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("$ref"), str):
                refs.append(node["$ref"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(SPEC)
    assert refs
    for ref in refs:
        assert ref.startswith("#/components/schemas/"), ref
        assert ref.rsplit("/", 1)[-1] in schemas, ref
