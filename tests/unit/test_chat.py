import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Sequence

import pytest

from app.providers.llm import ChatMessage, FakeLLM, LLMUnavailable
from app.repositories.chunk_repository import ChunkRecord
from app.services.chat import REFUSAL, ChatEvent, answer_events, format_sse
from app.services.retrieval import RetrievedChunk


def _hit(text: str, index: int = 0, doc: uuid.UUID | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=doc or uuid.uuid4(),
        chunk_index=index,
        text=text,
        heading_path="Guide > Charging",
        page=None,
        score=1.0,
        rank=1,
    )


async def _events(
    items: Sequence[RetrievedChunk], llm: object, max_context_tokens: int = 2000
) -> list[ChatEvent]:
    return [
        event
        async for event in answer_events(
            "How long does charging take?",
            items,
            llm,  # type: ignore[arg-type]
            max_context_tokens=max_context_tokens,
            answer_max_tokens=64,
        )
    ]


@pytest.mark.asyncio
async def test_events_come_in_order_sources_tokens_citations_done() -> None:
    hit = _hit("Charging takes two hours.")
    llm = FakeLLM(["Two ", "hours [1]."])

    events = await _events([hit], llm)

    assert [e.event for e in events] == [
        "sources",
        "token",
        "token",
        "citations",
        "done",
    ]
    sources = events[0].data["sources"]
    assert sources == [
        {
            "number": 1,
            "chunk_id": str(hit.chunk_id),
            "document_id": str(hit.document_id),
            "chunk_index": 0,
            "heading_path": "Guide > Charging",
            "text": "Charging takes two hours.",
        }
    ]
    assert [e.data["text"] for e in events[1:3]] == ["Two ", "hours [1]."]
    assert events[3].data == {
        "citations": [
            {
                "number": 1,
                "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id),
            }
        ],
        "dropped": [],
    }
    assert events[4].data == {
        "answer": "Two hours [1].",
        "refused": False,
        "external_links": [],
        "skipped_chunks": 0,
    }
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_empty_retrieval_refuses_with_zero_llm_calls() -> None:
    llm = FakeLLM(["should never be used"])

    events = await _events([], llm)

    assert [e.event for e in events] == ["sources", "token", "citations", "done"]
    assert events[0].data == {"sources": []}
    assert events[1].data == {"text": REFUSAL}
    assert events[3].data["refused"] is True
    assert events[3].data["answer"] == REFUSAL
    assert llm.calls == []


@pytest.mark.asyncio
async def test_retrieval_with_nothing_inside_the_budget_also_refuses() -> None:
    llm = FakeLLM(["unused"])

    events = await _events([_hit("word " * 400)], llm, max_context_tokens=10)

    assert events[-1].data["refused"] is True
    assert events[-1].data["skipped_chunks"] == 1
    assert llm.calls == []


@pytest.mark.asyncio
async def test_an_invalid_citation_is_stripped_from_the_answer_and_reported() -> None:
    llm = FakeLLM(["Two hours [1][4]."])

    events = await _events([_hit("Charging takes two hours.")], llm)

    citations, done = events[-2], events[-1]
    assert [c["number"] for c in citations.data["citations"]] == [1]
    assert citations.data["dropped"] == [4]
    assert done.data["answer"] == "Two hours [1]."


@pytest.mark.asyncio
async def test_an_external_link_in_the_answer_is_reported_not_followed() -> None:
    url = "https://attacker.example/x.png?d=1"
    llm = FakeLLM([f"Two hours [1]. ![x]({url})"])

    events = await _events([_hit("Charging takes two hours.")], llm)

    assert events[-1].data["external_links"] == [url]


@pytest.mark.asyncio
async def test_neighbors_are_joined_around_the_hit_in_index_order() -> None:
    doc = uuid.uuid4()
    hit = _hit("middle", index=5, doc=doc)
    before = ChunkRecord(uuid.uuid4(), doc, 4, "before", None, None, 1)
    after = ChunkRecord(uuid.uuid4(), doc, 6, "after", None, None, 1)
    hit = RetrievedChunk(**{**hit.__dict__, "neighbors": (before, after)})
    llm = FakeLLM(["ok [1]."])

    events = await _events([hit], llm)

    assert events[0].data["sources"][0]["text"] == "before\n\nmiddle\n\nafter"
    prompt = llm.calls[0][1].content
    assert "before\n\nmiddle\n\nafter" in prompt


class _FailingLLM:
    name = "failing"

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        yield "Two "
        raise LLMUnavailable("Ollama is unreachable (ConnectError)")


@pytest.mark.asyncio
async def test_a_provider_failure_mid_stream_ends_with_an_error_event() -> None:
    events = await _events([_hit("Charging takes two hours.")], _FailingLLM())

    assert [e.event for e in events] == ["sources", "token", "error"]
    assert events[-1].data == {
        "code": "llm_unavailable",
        "message": "The answer service is unavailable; try again later.",
    }


class _TrackingLLM:
    name = "tracking"

    def __init__(self) -> None:
        self.closed = False

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        try:
            for token in ["a", "b", "c", "d"]:
                yield token
        finally:
            self.closed = True


@pytest.mark.asyncio
async def test_closing_the_event_stream_early_closes_the_llm_stream() -> None:
    # What happens on client disconnect: the server stops iterating and closes us.
    llm = _TrackingLLM()
    stream = answer_events(
        "q",
        [_hit("Charging takes two hours.")],
        llm,  # type: ignore[arg-type]
        max_context_tokens=2000,
        answer_max_tokens=64,
    )

    assert (await anext(stream)).event == "sources"
    assert (await anext(stream)).data == {"text": "a"}
    await stream.aclose()

    assert llm.closed is True


def test_format_sse_keeps_a_newline_inside_a_token_on_one_data_line() -> None:
    frame = format_sse(ChatEvent("token", {"text": "line one\nline two"}))

    assert frame == 'event: token\ndata: {"text": "line one\\nline two"}\n\n'
    data_line = frame.split("\n")[1]
    assert json.loads(data_line.removeprefix("data: ")) == {
        "text": "line one\nline two"
    }


# --- M5 security review fixes -----------------------------------------------------


class _BrokenLLM:
    """A provider bug: malformed JSON surfacing as TypeError, not an LLMError."""

    name = "broken"

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        yield "Two "
        raise TypeError("'NoneType' object is not subscriptable")


@pytest.mark.asyncio
async def test_an_unexpected_exception_mid_stream_still_ends_with_an_error_event() -> (
    None
):
    events = await _events([_hit("Charging takes two hours.")], _BrokenLLM())

    assert [e.event for e in events] == ["sources", "token", "error"]
    assert events[-1].data == {
        "code": "llm_error",
        "message": "The answer could not be generated.",
    }


class _SlowLLM:
    name = "slow"

    def __init__(self) -> None:
        self.closed = False

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        try:
            yield "Two "
            await asyncio.sleep(60)
            yield "never"
        finally:
            self.closed = True


@pytest.mark.asyncio
async def test_an_answer_past_the_total_deadline_ends_with_a_timeout_error() -> None:
    llm = _SlowLLM()

    events = [
        event
        async for event in answer_events(
            "q",
            [_hit("Charging takes two hours.")],
            llm,  # type: ignore[arg-type]
            max_context_tokens=2000,
            answer_max_tokens=64,
            deadline_seconds=0.2,
        )
    ]

    assert [e.event for e in events] == ["sources", "token", "error"]
    assert events[-1].data["code"] == "llm_timeout"
    assert llm.closed is True


@pytest.mark.asyncio
async def test_cancelling_the_request_task_closes_the_llm_stream() -> None:
    # What Starlette does on client disconnect: cancel the task iterating the stream.
    llm = _SlowLLM()
    first_token = asyncio.Event()

    async def consume() -> None:
        async for event in answer_events(
            "q",
            [_hit("Charging takes two hours.")],
            llm,  # type: ignore[arg-type]
            max_context_tokens=2000,
            answer_max_tokens=64,
        ):
            if event.event == "token":
                first_token.set()

    task = asyncio.create_task(consume())
    await first_token.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert llm.closed is True


@pytest.mark.asyncio
async def test_when_every_answer_slot_is_taken_the_reply_is_busy_with_no_llm_call() -> (
    None
):
    slots = asyncio.Semaphore(1)
    await slots.acquire()
    llm = FakeLLM(["unused"])

    events = [
        event
        async for event in answer_events(
            "q",
            [_hit("Charging takes two hours.")],
            llm,
            max_context_tokens=2000,
            answer_max_tokens=64,
            slots=slots,
        )
    ]

    assert [e.event for e in events] == ["error"]
    assert events[0].data["code"] == "llm_busy"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_a_refusal_needs_no_answer_slot() -> None:
    slots = asyncio.Semaphore(1)
    await slots.acquire()

    events = [
        event
        async for event in answer_events(
            "q",
            [],
            FakeLLM([]),
            max_context_tokens=2000,
            answer_max_tokens=64,
            slots=slots,
        )
    ]

    assert events[-1].data["refused"] is True


@pytest.mark.asyncio
async def test_an_answer_releases_its_slot_when_done() -> None:
    slots = asyncio.Semaphore(1)

    await _consume_with_slots(slots)
    await _consume_with_slots(slots)

    assert not slots.locked()


async def _consume_with_slots(slots: asyncio.Semaphore) -> None:
    async for _event in answer_events(
        "q",
        [_hit("Charging takes two hours.")],
        FakeLLM(["ok [1]."]),
        max_context_tokens=2000,
        answer_max_tokens=64,
        slots=slots,
    ):
        pass


@pytest.mark.asyncio
async def test_done_answer_has_echoed_prompt_wrappers_stripped() -> None:
    echoed = (
        "<document id='1'>\nCharging takes two hours.\n</document>\n\nTwo hours [1]."
    )
    llm = FakeLLM([echoed])

    events = await _events([_hit("Charging takes two hours.")], llm)

    # Raw tokens stay as streamed; done.answer is the cleaned, authoritative text.
    assert events[1].data == {"text": echoed}
    assert events[-1].data["answer"] == "Charging takes two hours.\n\nTwo hours [1]."
    assert [c["number"] for c in events[-2].data["citations"]] == [1]
