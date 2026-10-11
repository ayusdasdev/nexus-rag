"""span() and the request-scoped trace (M9 9.1)."""

import asyncio

import pytest

from app.core import tracing


def test_a_span_records_its_name_duration_and_attributes_into_the_trace() -> None:
    with tracing.traced("req-1") as trace:
        with tracing.span("dense_search", hits=40):
            pass
        tracing.record("rerank", 12.5, candidates=50)

    assert trace.request_id == "req-1"
    assert [(s.name, s.attributes) for s in trace.spans] == [
        ("dense_search", {"hits": 40}),
        ("rerank", {"candidates": 50}),
    ]
    assert trace.spans[0].ms >= 0 and trace.spans[1].ms == 12.5
    assert tracing.current_trace() is None


def test_outside_a_trace_spans_are_harmless_and_record_nothing() -> None:
    with tracing.span("orphan"):
        pass
    tracing.record("orphan", 1.0)

    assert tracing.current_trace() is None


def test_a_span_is_recorded_when_its_body_fails_and_the_error_propagates() -> None:
    with (
        tracing.traced("req-2") as trace,
        pytest.raises(ValueError),
        tracing.span("generate"),
    ):
        raise ValueError("model text that must not be stored")

    (span,) = trace.spans
    assert span.name == "generate" and span.attributes == {"error": "ValueError"}


def test_spans_inside_awaited_code_land_in_the_same_trace() -> None:
    async def stage(name: str) -> None:
        with tracing.span(name):
            await asyncio.sleep(0)

    async def run() -> tracing.RequestTrace:
        with tracing.traced("req-3") as trace:
            await stage("embed_query")
            await stage("dense_search")
        return trace

    trace = asyncio.run(run())

    assert [s.name for s in trace.spans] == ["embed_query", "dense_search"]


def test_the_trace_summarises_milliseconds_per_stage() -> None:
    with tracing.traced("req-4") as trace:
        tracing.record("rerank", 10.0)
        tracing.record("rerank", 5.0)
        tracing.record("generate", 2.0)

    assert trace.stage_ms() == {"rerank": 15.0, "generate": 2.0}
