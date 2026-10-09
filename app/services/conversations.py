"""Conversation turns on top of the M5 chat pipeline (guide 6.3, ADR-0009)."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from itertools import pairwise
from typing import Any

from app.repositories.conversation_repository import MessageRecord
from app.services.chat import ChatEvent
from app.services.generation import (
    HistoryTurn,
    parse_citations,
    strip_prompt_scaffolding,
)

logger = logging.getLogger(__name__)

# What a stored assistant message keeps of each source. Chunk text is left out on purpose:
# a deleted document's text must not live on inside old messages.
_STORED_SOURCE_FIELDS = (
    "number",
    "chunk_id",
    "document_id",
    "chunk_index",
    "heading_path",
)

SaveAssistant = Callable[..., Awaitable[object]]


def stored_sources(sources: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: s[k] for k in _STORED_SOURCE_FIELDS if k in s} for s in sources]


def history_turns(messages: Sequence[MessageRecord]) -> list[HistoryTurn]:
    """Earlier answered turns, oldest first, as user/assistant pairs.

    A question without a complete answer (failed, truncated) is left out with its answer,
    so roles always alternate. Old [N] citation numbers are stripped from answers: they
    referred to that turn's sources, not the current ones.
    """
    turns: list[HistoryTurn] = []
    for question, answer in pairwise(messages):
        if (
            question.role == "user"
            and answer.role == "assistant"
            and not answer.truncated
        ):
            turns.append(HistoryTurn(role="user", content=question.content))
            cleaned = parse_citations(answer.content, source_count=0).text
            turns.append(HistoryTurn(role="assistant", content=cleaned))
    return turns


async def persisted_events(
    events: AsyncGenerator[ChatEvent, None],
    *,
    save: SaveAssistant,
    model: str,
    rewritten_query: str,
) -> AsyncGenerator[ChatEvent, None]:
    """Pass events through, then save the assistant message however the stream ends.

    A `done` event saves the cleaned answer. An error, or the client going away, saves the
    text streamed so far with truncated=True. The save is shielded, so a cancelled request
    still records it.
    """
    parts: list[str] = []
    sources: list[dict[str, Any]] = []
    answer: str | None = None
    try:
        async for event in events:
            if event.event == "sources":
                sources = stored_sources(event.data["sources"])
            elif event.event == "token":
                parts.append(event.data["text"])
            elif event.event == "done":
                answer = event.data["answer"]
            yield event
    finally:
        try:
            await asyncio.shield(events.aclose())
        except Exception as exc:  # noqa: BLE001 - the save below must still happen
            logger.error("closing the answer stream failed: %s", type(exc).__name__)
        if answer is None:
            # A partial answer gets the same cleaning as a finished one before it's kept.
            partial = parse_citations("".join(parts), source_count=len(sources)).text
            answer_text = strip_prompt_scaffolding(partial)
        else:
            answer_text = answer
        try:
            await asyncio.shield(
                save(
                    content=answer_text,
                    sources=sources,
                    rewritten_query=rewritten_query,
                    model=model,
                    truncated=answer is None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - never mask the stream's own outcome
            logger.error("saving the assistant message failed: %s", type(exc).__name__)
