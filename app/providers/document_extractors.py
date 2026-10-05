from dataclasses import dataclass
from pathlib import Path

import pymupdf4llm
import trafilatura


@dataclass(frozen=True)
class PdfPage:
    page_number: int
    markdown: str


@dataclass(frozen=True)
class PdfExtraction:
    pages: list[PdfPage]
    title: str | None


def extract_pdf(path: Path) -> PdfExtraction:
    chunks = pymupdf4llm.to_markdown(str(path), page_chunks=True)
    pages = [
        PdfPage(
            page_number=int(chunk["metadata"]["page_number"]), markdown=chunk["text"]
        )
        for chunk in chunks
    ]
    title = chunks[0]["metadata"].get("title") if chunks else None
    return PdfExtraction(pages=pages, title=title or None)


def extract_html(data: bytes) -> tuple[str | None, str | None]:
    markdown = trafilatura.extract(
        data, output_format="markdown", include_tables=True, include_links=False
    )
    metadata = trafilatura.extract_metadata(data)
    title = metadata.title if metadata is not None else None
    return markdown, title
