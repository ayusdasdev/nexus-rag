"""The chat pipeline after retrieval: prompt -> LLM stream -> validated citations.

Emits the SSE events of ADR-0008: sources, token*, citations, done (or error).
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass
from typing import Any

from app.core.tracing import record
from app.providers.llm import (
    LLMError,
    LLMNotConfigured,
    LLMProvider,
    LLMRateLimited,
    LLMRefused,
    LLMRequestRejected,
    LLMUnavailable,
)
from app.services.generation import (
    ContextChunk,
    HistoryTurn,
    approx_tokens,
    build_messages,
    find_external_links,
    parse_citations,
    strip_prompt_scaffolding,
)
from app.services.retrieval import RetrievedChunk, expanded_text

logger = logging.getLogger(__name__)

# Same wording the system prompt asks the model to use when the documents don't answer.
REFUSAL = "I can't answer that from the provided documents."

# Client-facing (code, message) per provider failure. Provider detail stays in the logs.
_ERRORS: list[tuple[type[LLMError], str, str]] = [
    (LLMRateLimited, "llm_rate_limited", "The answer service is busy; retry shortly."),
    (
        LLMUnavailable,
        "llm_unavailable",
        "The answer service is unavailable; try again later.",
    ),
    (LLMRefused, "llm_refused", "The model declined to answer this question."),
    (LLMRequestRejected, "llm_rejected", "The answer service rejected the request."),
    (LLMNotConfigured, "llm_not_configured", "The answer service is not configured."),
]


@dataclass(frozen=True)
class ChatEvent:
    event: str
    data: dict[str, Any]


def format_sse(event: ChatEvent) -> str:
    """One SSE frame. JSON keeps any newline in the data on a single data: line."""
    return f"event: {event.event}\ndata: {json.dumps(event.data)}\n\n"


def _context(item: RetrievedChunk) -> ContextChunk:
    return ContextChunk(
        chunk_id=item.chunk_id,
        document_id=item.document_id,
        text=expanded_text(item),
        heading_path=item.heading_path,
    )


_GENERIC_ERROR = ChatEvent(
    "error", {"code": "llm_error", "message": "The answer could not be generated."}
)
_TIMEOUT_ERROR = ChatEvent(
    "error", {"code": "llm_timeout", "message": "The answer took too long; try again."}
)
_BUSY_ERROR = ChatEvent(
    "error",
    {"code": "llm_busy", "message": "The answer service is busy; retry shortly."},
)


def _error_event(exc: LLMError) -> ChatEvent:
    for kind, code, message in _ERRORS:
        if isinstance(exc, kind):
            return ChatEvent("error", {"code": code, "message": message})
    return _GENERIC_ERROR


async def answer_events(
    question: str,
    items: Sequence[RetrievedChunk],
    llm: LLMProvider,
    *,
    max_context_tokens: int,
    answer_max_tokens: int,
    deadline_seconds: float | None = None,
    slots: asyncio.Semaphore | None = None,
    history: Sequence[HistoryTurn] = (),
    rewritten_query: str | None = None,
) -> AsyncGenerator[ChatEvent, None]:
    """Events for one answer. items are tenant-scoped retrieval results, best first.

    No usable context means a refusal with zero LLM calls. slots caps concurrent LLM
    answers: when none is free the only event is a busy error, with no LLM call.
    deadline_seconds bounds the whole answer, not each read. Closing or cancelling this
    generator early (client disconnect) closes the LLM stream with it.
    """
    built = build_messages(
        question,
        [_context(item) for item in items],
        max_context_tokens=max_context_tokens,
        history=history,
    )
    if built.sources and slots is not None and slots.locked():
        yield _BUSY_ERROR
        return
    by_chunk = {item.chunk_id: item for item in items}
    sources: dict[str, Any] = {
        "sources": [
            {
                "number": number,
                "chunk_id": str(source.chunk_id),
                "document_id": str(source.document_id),
                "chunk_index": by_chunk[source.chunk_id].chunk_index,
                "heading_path": source.heading_path,
                "text": source.text,
            }
            for number, source in enumerate(built.sources, start=1)
        ]
    }
    if rewritten_query is not None:
        # Conversations show the query retrieval actually used (guide 6.3).
        sources["rewritten_query"] = rewritten_query
    yield ChatEvent("sources", sources)

    if not built.sources:
        yield ChatEvent("token", {"text": REFUSAL})
        yield ChatEvent("citations", {"citations": [], "dropped": [], "malformed": []})
        yield ChatEvent(
            "done",
            {
                "answer": REFUSAL,
                "refused": True,
                "external_links": [],
                "skipped_chunks": built.skipped,
            },
        )
        return

    slot: AbstractAsyncContextManager[object] = slots if slots else nullcontext()
    async with slot:
        parts: list[str] = []
        stream = llm.stream(built.messages, max_tokens=answer_max_tokens)
        loop = asyncio.get_running_loop()
        deadline = None if deadline_seconds is None else loop.time() + deadline_seconds
        started = time.perf_counter()
        span_attributes: dict[str, object] = {
            "model": llm.name,
            "sources": len(built.sources),
        }
        try:
            while True:
                # The deadline wraps only the await, never our own yield.
                async with asyncio.timeout_at(deadline):
                    try:
                        token = await anext(stream)
                    except StopAsyncIteration:
                        break
                if not parts:
                    record("llm_first_token", (time.perf_counter() - started) * 1000)
                parts.append(token)
                yield ChatEvent("token", {"text": token})
        except TimeoutError:
            logger.warning("LLM %s passed the %ss deadline", llm.name, deadline_seconds)
            span_attributes["error"] = "TimeoutError"
            yield _TIMEOUT_ERROR
            return
        except LLMError as exc:
            # By type only: provider error text can echo prompt or document fragments.
            logger.warning("LLM %s failed: %s", llm.name, type(exc).__name__)
            span_attributes["error"] = type(exc).__name__
            yield _error_event(exc)
            return
        except Exception as exc:  # noqa: BLE001 - last resort, see comment below
            # A provider bug (e.g. malformed JSON) still ends the stream cleanly.
            logger.error("LLM %s raised %s", llm.name, type(exc).__name__)
            span_attributes["error"] = type(exc).__name__
            yield _GENERIC_ERROR
            return
        finally:
            # Estimated like the context budget (chars / 4); providers don't report usage.
            span_attributes["prompt_tokens"] = sum(
                approx_tokens(m.content) for m in built.messages
            )
            span_attributes["completion_tokens"] = approx_tokens("".join(parts))
            record(
                "generate", (time.perf_counter() - started) * 1000, **span_attributes
            )
            # Shielded so a cancelled request still closes the upstream connection.
            await asyncio.shield(stream.aclose())

    citations = parse_citations("".join(parts), source_count=len(built.sources))
    answer = strip_prompt_scaffolding(citations.text)
    yield ChatEvent(
        "citations",
        {
            "citations": [
                {
                    "number": n,
                    "chunk_id": str(built.sources[n - 1].chunk_id),
                    "document_id": str(built.sources[n - 1].document_id),
                }
                for n in citations.numbers
            ],
            "dropped": citations.dropped,
            "malformed": citations.malformed,
        },
    )
    yield ChatEvent(
        "done",
        {
            "answer": answer,
            "refused": answer == REFUSAL,
            "external_links": find_external_links(answer),
            "skipped_chunks": built.skipped,
        },
    )
