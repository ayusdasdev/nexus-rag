from pathlib import Path

import pytest

from app.providers.tokenizer import BgeTokenizer, is_cached
from app.services.chunking import chunk_markdown
from app.services.parsing import parse

SAMPLES = Path(__file__).resolve().parents[2] / "sample_docs"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_cached() or not (SAMPLES / "01_text_heavy.pdf").exists(),
        reason="needs the cached BGE tokenizer and sample_docs (make sample-docs)",
    ),
]


def _chunks(name: str):  # type: ignore[no-untyped-def]
    tokenizer = BgeTokenizer()
    parsed = parse(SAMPLES / name, "application/pdf")
    return chunk_markdown(parsed.markdown, tokenizer, max_tokens=350, overlap=50)


def test_text_heavy_heading_paths_have_no_bold_markers() -> None:
    chunks = _chunks("01_text_heavy.pdf")

    assert chunks
    assert all("**" not in (c.heading_path or "") for c in chunks)
    assert any(
        c.heading_path == "Nexus Widgets Deployment Guide > 1. Introduction"
        for c in chunks
    )


def test_two_column_running_header_is_not_a_heading_path_or_chunk_text() -> None:
    chunks = _chunks("03_two_column.pdf")

    assert chunks
    for chunk in chunks:
        assert "NEXUS-RUNNING-HEADER" not in (chunk.heading_path or "")
        assert "NEXUS-RUNNING-HEADER" not in chunk.text
        assert "NEXUS-CONFIDENTIAL-FOOTER" not in chunk.text
