from pathlib import Path

import pytest

from app.services.parsing import (
    NoExtractableText,
    PageSpan,
    ParsedDocument,
    UnsupportedContentType,
    check_pdf_text,
    parse,
    strip_running_lines,
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


SAMPLES = Path(__file__).resolve().parents[2] / "sample_docs"
needs_samples = pytest.mark.skipif(
    not (SAMPLES / "01_text_heavy.pdf").exists(),
    reason="sample_docs not generated; run make sample-docs",
)


@needs_samples
def test_pdf_heading_lines_have_no_bold_markers() -> None:
    markdown = parse(SAMPLES / "01_text_heavy.pdf", "application/pdf").markdown

    assert "**" not in markdown
    assert "## 1. Introduction" in markdown
    assert "# Nexus Widgets Deployment Guide" in markdown


@needs_samples
def test_two_column_running_header_and_footer_are_removed_and_content_kept() -> None:
    markdown = parse(SAMPLES / "03_two_column.pdf", "application/pdf").markdown

    assert "NEXUS-RUNNING-HEADER" not in markdown
    assert "NEXUS-CONFIDENTIAL-FOOTER" not in markdown
    assert "LEFT-01" in markdown
    assert "RIGHT-12" in markdown


def _text(*lines: str) -> str:
    return "\n".join(lines)


def _page(index: int, running: str | None) -> str:
    """Five lines: the running line (if any) at the top, unique body lines elsewhere."""
    lines = [
        f"body {index} top",
        f"body {index} second",
        f"body {index} middle",
        f"body {index} fourth",
        f"body {index} bottom",
    ]
    if running is not None:
        lines.insert(0, running)
    return "\n".join(lines)


def _kept(index: int) -> str:
    return _text(
        f"body {index} top",
        f"body {index} second",
        f"body {index} middle",
        f"body {index} fourth",
        f"body {index} bottom",
    )


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        pytest.param(
            [_page(i, "HDR") for i in range(3)],
            [_kept(i) for i in range(3)],
            id="header_on_all_three_pages_is_removed",
        ),
        pytest.param(
            [_page(i, "HDR") for i in range(2)],
            [_page(i, "HDR") for i in range(2)],
            id="two_pages_are_untouched",
        ),
        pytest.param(
            [_page(0, "HDR")],
            [_page(0, "HDR")],
            id="single_page_is_untouched",
        ),
        pytest.param(
            [_page(0, "HDR"), _page(1, "HDR"), _page(2, None)],
            [_page(0, "HDR"), _page(1, "HDR"), _page(2, None)],
            id="header_on_two_of_three_pages_is_below_80_percent",
        ),
        pytest.param(
            [
                _page(0, "HDR"),
                _page(1, "HDR"),
                _page(2, "HDR"),
                _page(3, "HDR"),
                _page(4, None),
            ],
            [_kept(0), _kept(1), _kept(2), _kept(3), _page(4, None)],
            id="header_on_four_of_five_pages_is_exactly_80_percent",
        ),
        pytest.param(
            [
                _page(0, "HDR"),
                _page(1, "HDR"),
                _page(2, None),
                _page(3, None),
                _page(4, None),
            ],
            [
                _page(0, "HDR"),
                _page(1, "HDR"),
                _page(2, None),
                _page(3, None),
                _page(4, None),
            ],
            id="header_on_two_of_five_pages_is_below_80_percent",
        ),
        pytest.param(
            [_page(0, "# **HDR**"), _page(1, "**HDR**"), _page(2, "HDR")],
            [_kept(0), _kept(1), _kept(2)],
            id="bold_and_heading_markup_is_ignored_when_matching",
        ),
        pytest.param(
            [
                _text(
                    "body 0 top",
                    "body 0 second",
                    "body 0 middle",
                    "body 0 bottom",
                    "FOOT",
                ),
                _text(
                    "body 1 top",
                    "body 1 second",
                    "body 1 middle",
                    "body 1 bottom",
                    "FOOT",
                ),
                _text(
                    "body 2 top",
                    "body 2 second",
                    "body 2 middle",
                    "body 2 bottom",
                    "FOOT",
                ),
            ],
            [
                _text("body 0 top", "body 0 second", "body 0 middle", "body 0 bottom"),
                _text("body 1 top", "body 1 second", "body 1 middle", "body 1 bottom"),
                _text("body 2 top", "body 2 second", "body 2 middle", "body 2 bottom"),
            ],
            id="repeated_bottom_line_is_removed",
        ),
        pytest.param(
            [
                _text("intro 0", "para 0a", "| Plan | Price |", "para 0b", "end 0"),
                _text("intro 1", "para 1a", "| Plan | Price |", "para 1b", "end 1"),
                _text("intro 2", "para 2a", "| Plan | Price |", "para 2b", "end 2"),
            ],
            [
                _text("intro 0", "para 0a", "| Plan | Price |", "para 0b", "end 0"),
                _text("intro 1", "para 1a", "| Plan | Price |", "para 1b", "end 1"),
                _text("intro 2", "para 2a", "| Plan | Price |", "para 2b", "end 2"),
            ],
            id="repeated_table_header_in_middle_of_page_is_kept",
        ),
    ],
)
def test_strip_running_lines(pages: list[str], expected: list[str]) -> None:
    assert strip_running_lines(pages) == expected
