"""The chat pipeline after retrieval: prompt -> LLM stream -> validated citations.

Emits the SSE events of ADR-0008: sources, token*, citations, done (or error).
"""

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any

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
    build_messages,
    find_external_links,
    parse_citations,
)
from app.services.retrieval import RetrievedChunk

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
    before = [n.text for n in item.neighbors if n.chunk_index < item.chunk_index]
    after = [n.text for n in item.neighbors if n.chunk_index > item.chunk_index]
    return ContextChunk(
        chunk_id=item.chunk_id,
        document_id=item.document_id,
        text="\n\n".join([*before, item.text, *after]),
        heading_path=item.heading_path,
    )


def _error_event(exc: LLMError) -> ChatEvent:
    for kind, code, message in _ERRORS:
        if isinstance(exc, kind):
            return ChatEvent("error", {"code": code, "message": message})
    return ChatEvent(
        "error", {"code": "llm_error", "message": "The answer could not be generated."}
    )


async def answer_events(
    question: str,
    items: Sequence[RetrievedChunk],
    llm: LLMProvider,
    *,
    max_context_tokens: int,
    answer_max_tokens: int,
) -> AsyncGenerator[ChatEvent, None]:
    """Events for one answer. items are tenant-scoped retrieval results, best first.

    No usable context means a refusal with zero LLM calls. Closing this generator early
    (client disconnect) closes the LLM stream with it.
    """
    built = build_messages(
        question,
        [_context(item) for item in items],
        max_context_tokens=max_context_tokens,
    )
    by_chunk = {item.chunk_id: item for item in items}
    yield ChatEvent(
        "sources",
        {
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
        },
    )

    if not built.sources:
        yield ChatEvent("token", {"text": REFUSAL})
        yield ChatEvent("citations", {"citations": [], "dropped": []})
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

    parts: list[str] = []
    stream = llm.stream(built.messages, max_tokens=answer_max_tokens)
    try:
        async for token in stream:
            parts.append(token)
            yield ChatEvent("token", {"text": token})
    except LLMError as exc:
        logger.warning("LLM %s failed: %s", llm.name, exc)
        yield _error_event(exc)
        return
    finally:
        await stream.aclose()

    citations = parse_citations("".join(parts), source_count=len(built.sources))
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
        },
    )
    yield ChatEvent(
        "done",
        {
            "answer": citations.text,
            "refused": citations.text.strip() == REFUSAL,
            "external_links": find_external_links(citations.text),
            "skipped_chunks": built.skipped,
        },
    )
