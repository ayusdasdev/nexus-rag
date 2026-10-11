"""One query trace per answer (M9 9.1): what was asked, how it was retrieved, what came back.

traced_answer passes the answer's events through unchanged and, however the stream ends
(done, error, or the client going away), writes one trace for the current request. The
write is shielded and its failure is logged by type only; it never breaks an answer.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from uuid import UUID

from app.core.tracing import current_trace
from app.services.chat import ChatEvent
from app.services.retrieval import Candidate, RetrieveResult

logger = logging.getLogger(__name__)

WriteTrace = Callable[..., Awaitable[object]]

# Candidates kept per stage in a trace: enough to see where a gold chunk ranked.
TRACE_CANDIDATES = 20


def _candidates(items: list[Candidate]) -> list[dict[str, object]]:
    return [
        {"chunk_id": str(c.chunk_id), "score": round(c.score, 6), "rank": c.rank}
        for c in items[:TRACE_CANDIDATES]
    ]


def retrieval_summary(result: RetrieveResult) -> dict[str, list[dict[str, object]]]:
    """Ids, scores and ranks per retrieval stage, and the final items. No text."""
    summary: dict[str, list[dict[str, object]]] = {
        "final": [
            {
                "chunk_id": str(item.chunk_id),
                "document_id": str(item.document_id),
                "score": round(item.score, 6),
                "rank": item.rank,
            }
            for item in result.items
        ]
    }
    if result.trace is not None:
        summary["dense"] = _candidates(result.trace.dense)
        summary["sparse"] = _candidates(result.trace.sparse)
        summary["fused"] = _candidates(result.trace.fused)
        summary["rerank"] = _candidates(result.trace.rerank)
    return summary


def _no_message() -> UUID | None:
    return None


async def traced_answer(
    events: AsyncGenerator[ChatEvent, None],
    *,
    write: WriteTrace,
    endpoint: str,
    query: str,
    rewritten_query: str | None,
    model: str,
    message_id: Callable[[], UUID | None] = _no_message,
) -> AsyncGenerator[ChatEvent, None]:
    trace = current_trace()
    answer: str | None = None
    error: str | None = None
    try:
        async for event in events:
            if event.event == "done":
                answer = event.data["answer"]
            elif event.event == "error":
                error = event.data["code"]
            yield event
    except (GeneratorExit, asyncio.CancelledError):
        if answer is None and error is None:
            error = "disconnected"
        raise
    finally:
        # Close the inner stream first, so a conversation's message is saved (and has an
        # id) before the trace that points at it is written.
        await asyncio.shield(events.aclose())
        if answer is None and error is None:
            error = "incomplete"
        if trace is not None:
            generate = next(
                (s for s in reversed(trace.spans) if s.name == "generate"), None
            )
            tokens = generate.attributes if generate is not None else {}
            try:
                await asyncio.shield(
                    write(
                        request_id=trace.request_id or "",
                        endpoint=endpoint,
                        query=query,
                        rewritten_query=rewritten_query,
                        stages=trace.annotations.get("retrieval", {}),
                        latency_ms=trace.stage_ms(),
                        prompt_tokens=tokens.get("prompt_tokens"),
                        completion_tokens=tokens.get("completion_tokens"),
                        model=model,
                        answer=answer,
                        error=error,
                        message_id=message_id(),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a trace must never break an answer
                logger.error("writing the query trace failed: %s", type(exc).__name__)
