from pathlib import Path

import pytest

from app.services.parsing import (
    NoExtractableText,
    PageSpan,
    ParsedDocument,
    UnsupportedContentType,
    check_pdf_text,
    parse,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_pdf_with_two_columns_and_table_keeps_reading_order_and_table() -> None:
    result = parse(FIXTURES / "two_column_table.pdf", "application/pdf")

    assert isinstance(result, ParsedDocument)
    assert result.title == "Storage tiers"
    assert "|Memory|0.1 ms|high|" in result.markdown
    assert result.markdown.index("Hot data lives") < result.markdown.index(
        "Eviction policy"
    )
    assert result.pages == [PageSpan(page=1, start=0, end=len(result.markdown))]


def test_html_keeps_headings_and_lists_and_drops_nav_and_footer() -> None:
    result = parse(FIXTURES / "nav_footer.html", "text/html")

    assert result.title == "Caching in practice"
    assert "# Caching in practice" in result.markdown
    assert "## Cache-aside" in result.markdown
    assert "- Simple to reason about" in result.markdown
    for noise in ("Subscribe to our newsletter", "Privacy", "Log in", "tracking"):
        assert noise not in result.markdown
    assert result.pages is None


def test_markdown_is_returned_as_is_with_nested_headings() -> None:
    source = FIXTURES / "nested_headings.md"

    result = parse(source, "text/plain")

    assert result.markdown == source.read_text(encoding="utf-8")
    assert "### Requirements" in result.markdown
    assert result.title == "Handbook"
    assert result.pages is None


def test_scanned_pdf_raises_no_extractable_text() -> None:
    with pytest.raises(NoExtractableText):
        parse(FIXTURES / "scanned.pdf", "application/pdf")


def test_pdf_with_text_under_200_characters_raises_no_extractable_text() -> None:
    with pytest.raises(NoExtractableText):
        parse(FIXTURES / "short_text.pdf", "application/pdf")


@pytest.mark.parametrize(
    ("text", "should_raise"),
    [
        ("", True),
        ("a" * 199, True),
        ("a" * 200, False),
        ("   " + "a" * 199 + "   ", True),
        ("a" * 500, False),
    ],
)
def test_check_pdf_text_threshold(text: str, should_raise: bool) -> None:
    if should_raise:
        with pytest.raises(NoExtractableText):
            check_pdf_text(text)
    else:
        check_pdf_text(text)


@pytest.mark.parametrize("content_type", ["image/png", "application/zip"])
def test_unsupported_content_type_raises(content_type: str) -> None:
    with pytest.raises(UnsupportedContentType):
        parse(FIXTURES / "nested_headings.md", content_type)
