"""Conversation memory and query rewriting (M6, ADR-0009).

trim_history keeps a token-budgeted sliding window. rewrite_query turns a follow-up into a
retrieval query: by a rule (default, no LLM call) or by the LLM (guide 6.2), never on the
first turn.
"""

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from contextlib import nullcontext

from app.core.config import RewriteMode
from app.providers.llm import ChatMessage, LLMError, LLMProvider
from app.services.generation import HistoryTurn, approx_tokens, neutralise
from app.services.prompts import load_prompt

logger = logging.getLogger(__name__)


__all__ = ["HistoryTurn", "is_follow_up", "rewrite_query", "trim_history"]

REWRITE_MAX_TOKENS = 64
_TAGS = "history|question"


def trim_history(
    turns: Sequence[HistoryTurn],
    max_tokens: int,
    count_tokens: Callable[[str], int] = approx_tokens,
) -> list[HistoryTurn]:
    """The most recent contiguous turns that fit max_tokens, oldest first.

    Stops at the first turn (going back in time) that doesn't fit, so the window never has
    a gap in it.
    """
    kept: list[HistoryTurn] = []
    used = 0
    for turn in reversed(turns):
        cost = count_tokens(turn.content)
        if used + cost > max_tokens:
            break
        kept.append(turn)
        used += cost
    return list(reversed(kept))


# Words that only make sense with an earlier turn, or a leading continuation. "there" is
# left out: it is usually existential ("Is there a warranty?").
_ANAPHOR = re.compile(r"\b(?:it|its|that|this|these|those|they|them)\b", re.IGNORECASE)
_CONTINUATION = re.compile(r"^\s*(?:and|also|what about|how about)\b", re.IGNORECASE)


def is_follow_up(question: str) -> bool:
    return bool(_ANAPHOR.search(question) or _CONTINUATION.search(question))


def _previous_user_question(history: Sequence[HistoryTurn]) -> str | None:
    for turn in reversed(history):
        if turn.role == "user":
            return turn.content
    return None


def _rule_rewrite(history: Sequence[HistoryTurn], question: str) -> str:
    previous = _previous_user_question(history)
    if previous is None or not is_follow_up(question):
        return question
    return f"{previous} {question}"


_LABEL = re.compile(
    r"^(?:standalone\s+|rewritten\s+|search\s+)?(?:query|question)\s*:\s*",
    re.IGNORECASE,
)


def _clean(output: str) -> str:
    """First non-empty line, without a "Query:" label or wrapping quotes."""
    line = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
    line = _LABEL.sub("", line)
    return line.strip().strip("\"'`").strip()


def _render(history: Sequence[HistoryTurn], question: str) -> list[ChatMessage]:
    lines = "\n".join(f"{t.role}: {neutralise(t.content, _TAGS)}" for t in history)
    values = {"history": lines, "question": neutralise(question, _TAGS)}
    user = re.sub(
        r"\{\{(history|question)\}\}",
        lambda match: values[match.group(1)],
        load_prompt("rewrite_user"),
    )
    return [
        ChatMessage(role="system", content=load_prompt("rewrite")),
        ChatMessage(role="user", content=user),
    ]


async def _llm_rewrite(
    history: Sequence[HistoryTurn],
    question: str,
    llm: LLMProvider,
    slots: asyncio.Semaphore | None,
    timeout_seconds: float | None,
) -> str:
    # The rewrite is an LLM call like an answer: it takes an answer slot and has a
    # deadline. Busy or slow means retrieving with the question as is (M6 review).
    if slots is not None and slots.locked():
        logger.warning("query rewrite skipped: every answer slot is taken")
        return question
    try:
        async with slots if slots is not None else nullcontext():
            async with asyncio.timeout(timeout_seconds):
                output = await llm.complete(
                    _render(history, question),
                    max_tokens=REWRITE_MAX_TOKENS,
                    temperature=0.0,
                )
    except TimeoutError:
        logger.warning("query rewrite passed its %ss deadline", timeout_seconds)
        return question
    except LLMError as exc:
        logger.warning(
            "query rewrite failed (%s); using the question", type(exc).__name__
        )
        return question
    rewritten = _clean(output)
    # A standalone query borrows its subject from the previous question, so the limit is
    # 3x (previous + current), not the guide's 3x the current question (ADR-0009).
    previous = _previous_user_question(history) or ""
    limit = 3 * len(f"{previous} {question}".strip())
    if not rewritten or len(rewritten) > limit:
        return question
    return rewritten


async def rewrite_query(
    history: Sequence[HistoryTurn],
    question: str,
    *,
    mode: RewriteMode,
    llm: LLMProvider,
    slots: asyncio.Semaphore | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """The query to retrieve with. The question itself on the first turn or when mode is off."""
    if not history or mode == "off":
        return question
    if mode == "rule":
        return _rule_rewrite(history, question)
    return await _llm_rewrite(history, question, llm, slots, timeout_seconds)
