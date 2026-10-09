"""persisted_events: the assistant message is saved however the stream ends."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from app.repositories.conversation_repository import MessageRecord
from app.services.chat import ChatEvent
from app.services.conversations import history_turns, persisted_events, stored_sources

SOURCES = [
    {
        "number": 1,
        "chunk_id": str(uuid.uuid4()),
        "document_id": str(uuid.uuid4()),
        "chunk_index": 0,
        "heading_path": "Guide",
        "text": "Charging takes two hours.",
    }
]


async def _stream(
    *events: ChatEvent, hang: bool = False
) -> AsyncGenerator[ChatEvent, None]:
    for event in events:
        yield event
    if hang:
        await asyncio.sleep(60)


class _Saved:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **fields: Any) -> None:
        self.calls.append(fields)


def test_stored_sources_keep_ids_and_headings_but_never_chunk_text() -> None:
    assert stored_sources(SOURCES) == [
        {k: v for k, v in SOURCES[0].items() if k != "text"}
    ]


@pytest.mark.asyncio
async def test_a_completed_answer_is_saved_with_its_metadata() -> None:
    save = _Saved()
    stream = _stream(
        ChatEvent("sources", {"sources": SOURCES, "rewritten_query": "q2"}),
        ChatEvent("token", {"text": "Two hours [1][9]."}),
        ChatEvent("citations", {"citations": [], "dropped": [9]}),
        ChatEvent("done", {"answer": "Two hours [1].", "refused": False}),
    )

    seen = [
        e.event
        async for e in persisted_events(
            stream, save=save, model="llama3.2:3b", rewritten_query="q2"
        )
    ]

    assert seen == ["sources", "token", "citations", "done"]
    assert save.calls == [
        {
            "content": "Two hours [1].",
            "sources": stored_sources(SOURCES),
            "rewritten_query": "q2",
            "model": "llama3.2:3b",
            "truncated": False,
        }
    ]


@pytest.mark.asyncio
async def test_an_error_mid_answer_saves_the_partial_text_as_truncated() -> None:
    save = _Saved()
    stream = _stream(
        ChatEvent("sources", {"sources": SOURCES}),
        ChatEvent("token", {"text": "Two "}),
        ChatEvent("error", {"code": "llm_unavailable", "message": "x"}),
    )

    _ = [
        e
        async for e in persisted_events(
            stream, save=save, model="m", rewritten_query="q"
        )
    ]

    assert save.calls[0]["content"] == "Two"
    assert save.calls[0]["truncated"] is True


@pytest.mark.asyncio
async def test_a_client_disconnect_saves_the_partial_text_as_truncated() -> None:
    save = _Saved()
    got_token = asyncio.Event()

    async def consume() -> None:
        stream = _stream(
            ChatEvent("sources", {"sources": SOURCES}),
            ChatEvent("token", {"text": "Two "}),
            hang=True,
        )
        async for event in persisted_events(
            stream, save=save, model="m", rewritten_query="q"
        ):
            if event.event == "token":
                got_token.set()

    task = asyncio.create_task(consume())
    await got_token.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert save.calls == [
        {
            "content": "Two",
            "sources": stored_sources(SOURCES),
            "rewritten_query": "q",
            "model": "m",
            "truncated": True,
        }
    ]


def test_history_turns_skip_truncated_answers_and_keep_order() -> None:
    from datetime import UTC, datetime

    from app.repositories.conversation_repository import MessageRecord

    def message(role: str, content: str, truncated: bool = False) -> MessageRecord:
        return MessageRecord(
            uuid.uuid4(),
            uuid.uuid4(),
            role,
            content,
            None,
            None,
            None,
            None,
            truncated,
            datetime.now(UTC),
        )

    records = [
        message("user", "q1"),
        message("assistant", "a1"),
        message("user", "q2"),
        message("assistant", "half an ans", truncated=True),
    ]

    # q2's answer is truncated, so q2 goes too: roles must alternate (M6 review, LOW-2).
    assert [(t.role, t.content) for t in history_turns(records)] == [
        ("user", "q1"),
        ("assistant", "a1"),
    ]


# --- M6 review, LOW-2 / INFO-1 ------------------------------------------------------


def _record(role: str, content: str, truncated: bool = False) -> MessageRecord:
    from datetime import UTC, datetime

    from app.repositories.conversation_repository import MessageRecord

    return MessageRecord(
        uuid.uuid4(),
        uuid.uuid4(),
        role,
        content,
        None,
        None,
        None,
        None,
        truncated,
        datetime.now(UTC),
    )


def test_history_resends_only_answered_turns_so_roles_alternate() -> None:
    records = [
        _record("user", "q1"),
        _record("assistant", "a1"),
        _record("user", "q2 never answered (retrieval failed)"),
        _record("user", "q3"),
        _record("assistant", "half", truncated=True),
        _record("user", "q4"),
        _record("assistant", "a4"),
    ]

    turns = history_turns(records)

    assert [(t.role, t.content) for t in turns] == [
        ("user", "q1"),
        ("assistant", "a1"),
        ("user", "q4"),
        ("assistant", "a4"),
    ]


def test_history_strips_old_citation_numbers_from_earlier_answers() -> None:
    turns = history_turns(
        [_record("user", "q"), _record("assistant", "Two hours [1][2].")]
    )

    assert turns[1].content == "Two hours."


@pytest.mark.asyncio
async def test_a_partial_answer_is_cleaned_before_it_is_saved() -> None:
    save = _Saved()
    stream = _stream(
        ChatEvent("sources", {"sources": SOURCES}),
        ChatEvent("token", {"text": "<document id='1'>\nTwo hours [1][9]"}),
        ChatEvent("error", {"code": "llm_timeout", "message": "x"}),
    )

    _ = [
        e
        async for e in persisted_events(
            stream, save=save, model="m", rewritten_query="q"
        )
    ]

    assert save.calls[0]["content"] == "Two hours [1]"
    assert save.calls[0]["truncated"] is True


@pytest.mark.asyncio
async def test_the_answer_is_saved_even_if_closing_the_stream_fails() -> None:
    save = _Saved()

    class Exploding:
        def __init__(self) -> None:
            self._events = iter([ChatEvent("sources", {"sources": SOURCES})])

        def __aiter__(self) -> "Exploding":
            return self

        async def __anext__(self) -> ChatEvent:
            try:
                return next(self._events)
            except StopIteration:
                raise StopAsyncIteration from None

        async def aclose(self) -> None:
            raise RuntimeError("close failed")

    _ = [
        e
        async for e in persisted_events(
            Exploding(),  # type: ignore[arg-type]
            save=save,
            model="m",
            rewritten_query="q",
        )
    ]

    assert len(save.calls) == 1
