"""Pure prompt building and answer post-processing for RAG generation (ADR-0007).

Nothing here does I/O except reading the prompt files, and nothing here fetches a URL.
"""

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.providers.llm import ChatMessage
from app.services.prompts import load_prompt


@dataclass(frozen=True)
class ContextChunk:
    chunk_id: UUID
    document_id: UUID
    text: str
    heading_path: str | None = None


@dataclass(frozen=True)
class BuiltPrompt:
    messages: list[ChatMessage]
    # The chunks actually sent, in order: sources[n - 1] is <document id='n'>.
    sources: list[ContextChunk]
    # Chunks left out because they didn't fit the context budget.
    skipped: int


@dataclass(frozen=True)
class Citations:
    text: str
    # Valid citation numbers in order of first use, each once.
    numbers: list[int]
    # Out-of-range numbers that were stripped from text, each once.
    dropped: list[int]


def approx_tokens(text: str) -> int:
    """About 4 characters per token: close enough for a budget, no tokenizer needed."""
    return math.ceil(len(text) / 4)


# A "<" that would open or close one of our own sections, inside untrusted text.
_DELIMITER = re.compile(r"<(?=\s*/?\s*(?:documents?|question)\b)", re.IGNORECASE)
_SLOT = re.compile(r"\{\{(documents|question)\}\}")


def _neutralise(text: str) -> str:
    """Untrusted text can't open or close our tags; everything else stays verbatim."""
    return _DELIMITER.sub("&lt;", text)


def _document_block(number: int, chunk: ContextChunk) -> str:
    lines = [f"<document id='{number}'>"]
    if chunk.heading_path:
        lines.append(f"Section: {_neutralise(chunk.heading_path)}")
    lines.append(_neutralise(chunk.text))
    lines.append("</document>")
    return "\n".join(lines)


def build_messages(
    question: str,
    chunks: Sequence[ContextChunk],
    *,
    max_context_tokens: int,
    count_tokens: Callable[[str], int] = approx_tokens,
) -> BuiltPrompt:
    """System rules plus one user message with numbered documents and the question.

    chunks come best-first. Each is added while it fits max_context_tokens (counting its
    heading and text); one that doesn't fit is skipped and later, smaller ones may still
    go in. Numbering is contiguous over what was sent.
    """
    sources: list[ContextChunk] = []
    used = 0
    for chunk in chunks:
        cost = count_tokens(chunk.text) + count_tokens(chunk.heading_path or "")
        if used + cost > max_context_tokens:
            continue
        sources.append(chunk)
        used += cost

    documents = "\n".join(
        _document_block(number, chunk) for number, chunk in enumerate(sources, start=1)
    )
    values = {"documents": documents, "question": _neutralise(question)}
    # One pass over the template only, so text inside a value is never re-expanded.
    user = _SLOT.sub(lambda match: values[match.group(1)], load_prompt("rag_user"))
    return BuiltPrompt(
        messages=[
            ChatMessage(role="system", content=load_prompt("rag_system")),
            ChatMessage(role="user", content=user),
        ],
        sources=sources,
        skipped=len(chunks) - len(sources),
    )


_CITATION = re.compile(r"(\s*)\[(\s*\d+\s*(?:,\s*\d+\s*)*)\]")


def parse_citations(text: str, source_count: int) -> Citations:
    """Keep citations to documents 1..source_count; strip and report any other number.

    Reads [1], [1][3] and [2, 3]. A citation left with no valid number is removed
    together with the whitespace before it.
    """
    numbers: list[int] = []
    dropped: list[int] = []

    def replace(match: re.Match[str]) -> str:
        cited = [int(part) for part in match.group(2).split(",")]
        kept = [n for n in cited if 1 <= n <= source_count]
        for n in cited:
            target = numbers if n in kept else dropped
            if n not in target:
                target.append(n)
        if len(kept) == len(cited):
            return match.group(0)
        if not kept:
            return ""
        return match.group(1) + "[" + ", ".join(str(n) for n in kept) + "]"

    return Citations(
        text=_CITATION.sub(replace, text), numbers=numbers, dropped=dropped
    )


_URL = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)


def find_external_links(text: str) -> list[str]:
    """Every http(s) URL in the answer, including Markdown image targets. Never fetched."""
    return [match.rstrip(".,;:!?") for match in _URL.findall(text)]
