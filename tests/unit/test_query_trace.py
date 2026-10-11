"""traced_answer: one query trace per answer, however the stream ends (M9 9.1)."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from app.core import tracing
from app.services.chat import ChatEvent
from app.services.query_trace import traced_answer

SOURCES = {"sources": [{"number": 1, "chunk_id": "c1", "text": "Two hours."}]}


async def _stream(*events: ChatEvent) -> AsyncGenerator[ChatEvent, None]:
    for event in events:
        yield event


def _done(answer: str) -> ChatEvent:
    return ChatEvent(
        "done",
        {"answer": answer, "refused": False, "external_links": [], "skipped_chunks": 0},
    )


class Writer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def __call__(self, **fields: Any) -> uuid.UUID:
        self.calls.append(fields)
        if self.fail:
            raise RuntimeError("database down, password hunter2")
        return uuid.uuid4()


async def _drain(events: AsyncGenerator[ChatEvent, None]) -> list[ChatEvent]:
    return [event async for event in events]


@pytest.mark.asyncio
async def test_a_finished_answer_is_written_once_with_everything_needed_to_replay_it() -> (
    None
):
    write = Writer()
    with tracing.traced("req-9") as trace:
        tracing.annotate(
            "retrieval", {"final": [{"chunk_id": "c1", "score": 0.9, "rank": 1}]}
        )
        tracing.record("rerank", 10.0)
        tracing.record("generate", 100.0, prompt_tokens=420, completion_tokens=7)
        events = await _drain(
            traced_answer(
                _stream(
                    ChatEvent("sources", SOURCES),
                    ChatEvent("token", {"text": "Two hours [1]."}),
                    _done("Two hours [1]."),
                ),
                write=write,
                endpoint="chat",
                query="How long?",
                rewritten_query=None,
                model="llama3.2:3b",
            )
        )

    assert [e.event for e in events] == ["sources", "token", "done"]
    (fields,) = write.calls
    assert fields == {
        "request_id": "req-9",
        "endpoint": "chat",
        "query": "How long?",
        "rewritten_query": None,
        "stages": {"final": [{"chunk_id": "c1", "score": 0.9, "rank": 1}]},
        "latency_ms": trace.stage_ms(),
        "prompt_tokens": 420,
        "completion_tokens": 7,
        "model": "llama3.2:3b",
        "answer": "Two hours [1].",
        "error": None,
        "message_id": None,
    }


@pytest.mark.asyncio
async def test_an_error_event_is_traced_with_its_code_and_no_answer() -> None:
    write = Writer()
    with tracing.traced("req"):
        await _drain(
            traced_answer(
                _stream(
                    ChatEvent("sources", SOURCES),
                    ChatEvent("error", {"code": "llm_unavailable", "message": "x"}),
                ),
                write=write,
                endpoint="chat",
                query="q",
                rewritten_query=None,
                model="m",
            )
        )

    (fields,) = write.calls
    assert (fields["answer"], fields["error"]) == (None, "llm_unavailable")


@pytest.mark.asyncio
async def test_a_client_that_goes_away_still_leaves_a_trace() -> None:
    write = Writer()
    with tracing.traced("req"):
        events = traced_answer(
            _stream(
                ChatEvent("sources", SOURCES),
                ChatEvent("token", {"text": "Two "}),
                _done("Two hours."),
            ),
            write=write,
            endpoint="chat",
            query="q",
            rewritten_query=None,
            model="m",
        )
        await anext(events)
        await events.aclose()

    (fields,) = write.calls
    assert (fields["answer"], fields["error"]) == (None, "disconnected")


@pytest.mark.asyncio
async def test_a_failed_trace_write_never_breaks_the_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with tracing.traced("req"):
        events = await _drain(
            traced_answer(
                _stream(ChatEvent("sources", SOURCES), _done("ok")),
                write=Writer(fail=True),
                endpoint="chat",
                query="q",
                rewritten_query=None,
                model="m",
            )
        )

    assert [e.event for e in events] == ["sources", "done"]
    assert "RuntimeError" in caplog.text and "hunter2" not in caplog.text


@pytest.mark.asyncio
async def test_a_conversation_turn_links_its_trace_to_the_saved_message() -> None:
    write = Writer()
    message_id = uuid.uuid4()
    with tracing.traced("req"):
        await _drain(
            traced_answer(
                _stream(ChatEvent("sources", SOURCES), _done("ok")),
                write=write,
                endpoint="conversation",
                query="And it?",
                rewritten_query="How long? And it?",
                model="m",
                message_id=lambda: message_id,
            )
        )

    (fields,) = write.calls
    assert fields["message_id"] == message_id
    assert fields["rewritten_query"] == "How long? And it?"


@pytest.mark.asyncio
async def test_without_a_request_trace_nothing_is_written() -> None:
    write = Writer()

    await _drain(
        traced_answer(
            _stream(_done("ok")),
            write=write,
            endpoint="chat",
            query="q",
            rewritten_query=None,
            model="m",
        )
    )

    assert write.calls == []


def test_annotate_outside_a_trace_is_harmless() -> None:
    tracing.annotate("retrieval", {"final": []})

    with tracing.traced("req") as trace:
        tracing.annotate("retrieval", {"final": [1]})

    assert trace.annotations == {"retrieval": {"final": [1]}}
