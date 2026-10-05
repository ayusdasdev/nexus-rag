import re
from dataclasses import dataclass
from pathlib import Path

from app.providers.document_extractors import extract_html, extract_pdf

PDF_MIN_CHARS = 200
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


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


def _parse_pdf(path: Path) -> ParsedDocument:
    extraction = extract_pdf(path)
    parts: list[str] = []
    spans: list[PageSpan] = []
    offset = 0
    for page in extraction.pages:
        text = page.markdown.strip()
        if not text:
            continue
        if parts:
            offset += len("\n\n")
        start = offset
        parts.append(text)
        offset += len(text)
        spans.append(PageSpan(page=page.page_number, start=start, end=offset))

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
