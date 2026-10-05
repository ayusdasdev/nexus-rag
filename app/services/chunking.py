import re
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


class Tokenizer(Protocol):
    @property
    def model_max_tokens(self) -> int: ...

    @property
    def special_token_overhead(self) -> int: ...

    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    heading_path: str | None
    chunk_index: int
    token_count: int
    page: int | None = None


def _split_blank_lines(text: str) -> list[str]:
    return re.split(r"\n\s*\n", text)


def _split_lines(text: str) -> list[str]:
    return text.split("\n")


def _split_sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", text)


def _split_words(text: str) -> list[str]:
    return text.split()


# (separator used when re-joining, how to split). Ordered coarse to fine.
_LEVELS: list[tuple[str, Callable[[str], list[str]]]] = [
    ("\n\n", _split_blank_lines),
    ("\n", _split_lines),
    (" ", _split_sentences),
    (" ", _split_words),
]


class _Budget:
    def __init__(self, tokenizer: Tokenizer, max_tokens: int) -> None:
        self._tokenizer = tokenizer
        self.max_tokens = max_tokens

    def count(self, text: str) -> int:
        return self._tokenizer.count(text)

    def fits(self, text: str) -> bool:
        return self.count(text) <= self.max_tokens


def _sections(md: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    stack: list[tuple[int, str]] = []
    path: str | None = None
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((path, body))
        buffer.clear()

    for line in md.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            buffer.append(line)
            continue
        heading = None if in_fence else _HEADING.match(line)
        if heading is None:
            buffer.append(line)
            continue
        flush()
        level = len(heading.group(1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading.group(2)))
        path = " > ".join(title for _, title in stack)
    flush()
    return sections


def _halve(text: str, budget: _Budget) -> list[str]:
    if budget.fits(text) or len(text) <= 1:
        return [text]
    middle = len(text) // 2
    return _halve(text[:middle], budget) + _halve(text[middle:], budget)


def _pack(pieces: list[str], separator: str, budget: _Budget) -> list[str]:
    packed: list[str] = []
    current: str | None = None
    for piece in pieces:
        if current is None:
            current = piece
            continue
        merged = current + separator + piece
        if budget.fits(merged):
            current = merged
        else:
            packed.append(current)
            current = piece
    if current is not None:
        packed.append(current)
    return packed


def _fit(text: str, level: int, pack: _Budget, limit: _Budget) -> list[str]:
    """Split text into pieces. Packing respects `pack`; a piece that fits `limit`
    is never split further, so a table row stays whole even above the pack budget."""
    if not text.strip():
        return []
    if pack.fits(text) or limit.fits(text):
        return [text]
    if level >= len(_LEVELS):
        return _halve(text, limit)
    separator, split = _LEVELS[level]
    pieces: list[str] = []
    for unit in split(text):
        if unit.strip():
            pieces.extend(_fit(unit, level + 1, pack, limit))
    return _pack(pieces, separator, pack)


def _drop_first(prefix: str) -> str:
    if "\n" in prefix:
        return prefix.split("\n", 1)[1]
    if " " in prefix:
        return prefix.split(" ", 1)[1]
    return ""


def _overlap_prefix(previous: str, budget: _Budget, overlap: int) -> str:
    lines = previous.split("\n")
    kept: list[str] = []
    for line in reversed(lines):
        candidate = "\n".join([line, *kept])
        if budget.count(candidate) > overlap:
            break
        kept.insert(0, line)
    if kept:
        return "\n".join(kept)
    # Never start a chunk mid-table-row: only prose may fall back to words.
    if lines[-1].lstrip().startswith("|"):
        return ""
    words: list[str] = []
    for word in reversed(lines[-1].split(" ")):
        candidate = " ".join([word, *words])
        if budget.count(candidate) > overlap:
            break
        words.insert(0, word)
    return " ".join(words)


def _with_overlap(parts: list[str], budget: _Budget, overlap: int) -> list[str]:
    if not parts:
        return []
    out = [parts[0]]
    for previous, current in pairwise(parts):
        prefix = _overlap_prefix(previous, budget, overlap) if overlap else ""
        while prefix and not budget.fits(prefix + "\n" + current):
            prefix = _drop_first(prefix)
        out.append(f"{prefix}\n{current}" if prefix else current)
    return out


def chunk_markdown(
    md: str,
    tokenizer: Tokenizer,
    max_tokens: int = 350,
    overlap: int = 50,
) -> list[ChunkDraft]:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if overlap < 0 or overlap >= max_tokens:
        raise ValueError("overlap must be >= 0 and smaller than max_tokens")
    if max_tokens + tokenizer.special_token_overhead > tokenizer.model_max_tokens:
        raise ValueError(
            "max_tokens plus special-token overhead exceeds the model limit"
        )

    # Bodies are packed into max_tokens - overlap so the overlap prefix always fits.
    body_budget = _Budget(tokenizer, max_tokens - overlap)
    budget = _Budget(tokenizer, max_tokens)
    drafts: list[ChunkDraft] = []
    for path, body in _sections(md):
        for text in _with_overlap(_fit(body, 0, body_budget, budget), budget, overlap):
            drafts.append(
                ChunkDraft(
                    text=text,
                    heading_path=path,
                    chunk_index=len(drafts),
                    token_count=budget.count(text),
                )
            )
    return drafts
