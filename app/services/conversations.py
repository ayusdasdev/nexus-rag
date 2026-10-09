"""Conversation turns on top of the M5 chat pipeline (guide 6.3, ADR-0009)."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from typing import Any

from app.repositories.conversation_repository import MessageRecord
from app.services.chat import ChatEvent
from app.services.generation import HistoryTurn

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
    """Earlier turns, oldest first. A truncated (unfinished) answer is not resent."""
    return [
        HistoryTurn(role="user" if m.role == "user" else "assistant", content=m.content)
        for m in messages
        if not (m.role == "assistant" and m.truncated)
    ]


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
        await asyncio.shield(events.aclose())
        try:
            await asyncio.shield(
                save(
                    content=answer if answer is not None else "".join(parts),
                    sources=sources,
                    rewritten_query=rewritten_query,
                    model=model,
                    truncated=answer is None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - never mask the stream's own outcome
            logger.error("saving the assistant message failed: %s", type(exc).__name__)
