import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.providers.document_extractors import extract_html, extract_pdf

PDF_MIN_CHARS = 200
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_HEADING_BOLD = re.compile(r"^(#{1,6}\s+)\*\*(.+?)\*\*\s*$")
_PARAGRAPH_BOLD = re.compile(r"^(\s*)\*\*(.+?)\*\*\s*$")

# A running header or footer must repeat on most pages, and sit at a page edge.
RUNNING_MIN_PAGES = 3
RUNNING_MIN_SHARE = 0.8
RUNNING_EDGE_LINES = 2


class NoExtractableText(Exception):
    pass


class UnsupportedContentType(Exception):
    pass


@dataclass(frozen=True)
class PageSpan:
    page: int
    start: int
    end: int


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    pages: list[PageSpan] | None
    title: str | None


def check_pdf_text(markdown: str) -> None:
    # A scanned PDF yields no text layer; a near-empty one is not worth chunking.
    if len(markdown.strip()) < PDF_MIN_CHARS:
        raise NoExtractableText


def parse(path: Path, content_type: str) -> ParsedDocument:
    if content_type == "application/pdf":
        return _parse_pdf(path)
    if content_type == "text/html":
        return _parse_html(path)
    if content_type == "text/plain":
        return _parse_text(path)
    raise UnsupportedContentType(content_type)


def _first_heading(markdown: str) -> str | None:
    match = _HEADING.search(markdown)
    return match.group(1) if match else None


def _unbold(line: str) -> str:
    heading = _HEADING_BOLD.match(line)
    if heading:
        return f"{heading.group(1)}{heading.group(2)}"
    paragraph = _PARAGRAPH_BOLD.match(line)
    if paragraph:
        return f"{paragraph.group(1)}{paragraph.group(2)}"
    return line


def _match_key(line: str) -> str:
    return re.sub(r"^[#\s*]+|[*\s]+$", "", line)


def _edge_indices(lines: list[str]) -> set[int]:
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    return set(nonempty[:RUNNING_EDGE_LINES]) | set(nonempty[-RUNNING_EDGE_LINES:])


def strip_running_lines(pages: list[str]) -> list[str]:
    """Remove a header or footer line that repeats at a page edge on most pages.

    Only documents with at least RUNNING_MIN_PAGES pages are changed. Only each page's
    first and last RUNNING_EDGE_LINES non-empty lines are candidates, so a repeated line in
    the middle of a page (such as a table header) is kept.
    """
    if len(pages) < RUNNING_MIN_PAGES:
        return list(pages)
    split = [page.split("\n") for page in pages]
    counts: Counter[str] = Counter()
    for lines in split:
        keys = {_match_key(lines[i]) for i in _edge_indices(lines)}
        counts.update(key for key in keys if key)
    threshold = RUNNING_MIN_SHARE * len(pages)
    running = {key for key, count in counts.items() if count >= threshold}
    result: list[str] = []
    for lines in split:
        edges = _edge_indices(lines)
        kept = [
            line
            for i, line in enumerate(lines)
            if not (i in edges and _match_key(line) in running)
        ]
        result.append("\n".join(kept))
    return result


def _parse_pdf(path: Path) -> ParsedDocument:
    extraction = extract_pdf(path)
    pages = strip_running_lines(
        [
            "\n".join(_unbold(line) for line in page.markdown.split("\n"))
            for page in extraction.pages
        ]
    )
    parts: list[str] = []
    spans: list[PageSpan] = []
    offset = 0
    for page_number, page_text in zip((p.page_number for p in extraction.pages), pages):
        text = page_text.strip()
        if not text:
            continue
        if parts:
            offset += len("\n\n")
        start = offset
        parts.append(text)
        offset += len(text)
        spans.append(PageSpan(page=page_number, start=start, end=offset))

    markdown = "\n\n".join(parts)
    check_pdf_text(markdown)
    return ParsedDocument(
        markdown=markdown,
        pages=spans,
        title=extraction.title or _first_heading(markdown),
    )


def _parse_html(path: Path) -> ParsedDocument:
    markdown, title = extract_html(path.read_bytes())
    if markdown is None or not markdown.strip():
        raise NoExtractableText
    return ParsedDocument(
        markdown=markdown, pages=None, title=title or _first_heading(markdown)
    )


def _parse_text(path: Path) -> ParsedDocument:
    text = path.read_bytes().decode("utf-8-sig")
    if not text.strip():
        raise NoExtractableText
    return ParsedDocument(markdown=text, pages=None, title=_first_heading(text))
