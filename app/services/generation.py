"""Pure prompt building and answer post-processing for RAG generation (ADR-0007).

Nothing here does I/O except reading the prompt files, and nothing here fetches a URL.
"""

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
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


# A "<" (or a fullwidth/small lookalike, optionally padded with zero-width characters)
# that would open or close one of our own sections, inside untrusted text.
_ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"


@lru_cache
def _delimiter(names: str) -> re.Pattern[str]:
    return re.compile(
        rf"[<\uff1c\ufe64][{_ZERO_WIDTH}]{{0,8}}"
        rf"(?=[\s{_ZERO_WIDTH}]{{0,8}}/?[\s{_ZERO_WIDTH}]{{0,8}}(?:{names})\b)",
        re.IGNORECASE,
    )


def neutralise(text: str, names: str = "documents?|question") -> str:
    """Untrusted text can't open or close our tags (names: a regex alternation of tag
    names); everything else stays verbatim."""
    return _delimiter(names).sub("&lt;", text)


def _neutralise(text: str) -> str:
    return neutralise(text)


_SLOT = re.compile(r"\{\{(documents|question)\}\}")


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


# Bounded everywhere, so matching stays linear on any model output (ReDoS fix), and a
# 5-digit-or-longer number is never a citation (int() of thousands of digits raises).
_NUM = r"\s{0,8}\d{1,4}\s{0,8}"
_CITATION = re.compile(rf"\[({_NUM}(?:,{_NUM}){{0,49}})\]")


def parse_citations(text: str, source_count: int) -> Citations:
    """Keep citations to documents 1..source_count; strip and report any other number.

    Reads [1], [1][3] and [2, 3]. A citation left with no valid number is removed
    together with the spaces before it.
    """
    numbers: list[int] = []
    dropped: list[int] = []
    out: list[str] = []
    last = 0
    for match in _CITATION.finditer(text):
        cited = [int(part) for part in match.group(1).split(",")]
        kept = [n for n in cited if 1 <= n <= source_count]
        for n in cited:
            target = numbers if n in kept else dropped
            if n not in target:
                target.append(n)
        before = text[last : match.start()]
        if len(kept) == len(cited):
            replacement = match.group(0)
        elif kept:
            replacement = "[" + ", ".join(str(n) for n in kept) + "]"
        else:
            replacement = ""
            before = before.rstrip(" \t")
        out.append(before)
        out.append(replacement)
        last = match.end()
    out.append(text[last:])
    return Citations(text="".join(out), numbers=numbers, dropped=dropped)


# Our own section tags echoed back by the model (seen with llama3.2:3b, M5 5.5 Q3), raw or
# in the &lt; form _neutralise produces. Bounded, so it stays linear on any output.
_SCAFFOLD_TAG = re.compile(
    r"(?:<|&lt;)[ \t]{0,4}/?[ \t]{0,4}(?:documents?|question)\b[^<>\n]{0,200}>[ \t]*\n?",
    re.IGNORECASE,
)
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


def strip_prompt_scaffolding(text: str) -> str:
    """Remove echoed <document ...>, </document>, <documents>, <question> wrappers (and their
    closing tags) from an answer. The text between them is kept."""
    without_tags = _SCAFFOLD_TAG.sub("", text)
    return _EXTRA_BLANK_LINES.sub("\n\n", without_tags).strip()


_URL = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)


def find_external_links(text: str) -> list[str]:
    """Every http(s) URL in the answer, including Markdown image targets. Never fetched."""
    return [match.rstrip(".,;:!?") for match in _URL.findall(text)]
