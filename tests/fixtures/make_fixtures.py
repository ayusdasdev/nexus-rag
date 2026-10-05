"""Regenerate the parser test fixtures. Run from the repo root:

uv run python tests/fixtures/make_fixtures.py
"""

from pathlib import Path

import pymupdf

FIXTURES = Path(__file__).resolve().parent

NESTED_MARKDOWN = """# Handbook

Overview paragraph that introduces the handbook.

## Setup

Install the tools before you start.

### Requirements

- Python 3.12
- Docker

### Steps

1. Clone the repository.
2. Run the bootstrap script.

## Usage

Run the service and open the dashboard.
"""

NAV_FOOTER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Caching in practice</title>
  <script>window.tracking = {id: "abc"};</script>
</head>
<body>
  <nav>
    <ul><li><a href="/">Home</a></li><li><a href="/blog">Blog</a></li><li><a href="/login">Log in</a></li></ul>
  </nav>
  <article>
    <h1>Caching in practice</h1>
    <p>A cache trades memory for latency. This article covers the three patterns that matter
    most in day-to-day services, and when each one is the right choice for a read-heavy path.</p>
    <h2>Cache-aside</h2>
    <p>The application checks the cache first and loads from the database on a miss.</p>
    <ul>
      <li>Simple to reason about</li>
      <li>Stale data is possible until the TTL expires</li>
    </ul>
    <h2>Write-through</h2>
    <p>Every write goes to the cache and the database together, so reads stay fresh.</p>
  </article>
  <aside><p>Subscribe to our newsletter for weekly posts.</p></aside>
  <footer>
    <p>Copyright 2026. <a href="/privacy">Privacy</a> <a href="/terms">Terms</a></p>
  </footer>
</body>
</html>
"""

_TABLE_ROWS = [
    ("Tier", "Latency", "Cost"),
    ("Memory", "0.1 ms", "high"),
    ("Redis", "0.5 ms", "medium"),
    ("Disk", "8 ms", "low"),
]


def make_two_column_table_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 60), "Storage tiers", fontsize=18)

    left = (
        "Hot data lives in memory so reads return in microseconds. "
        "Warm data sits in a network cache, a little slower but shared "
        "between instances. Cold data is read from disk and is the cheapest "
        "to keep around for audits and backups."
    )
    right = (
        "Eviction policy matters as much as capacity. Least recently used "
        "entries leave first, which suits most read-heavy workloads. Set a "
        "maximum size per tier so one tenant cannot fill the whole cache."
    )
    page.insert_textbox(pymupdf.Rect(72, 100, 290, 330), left, fontsize=10)
    page.insert_textbox(pymupdf.Rect(322, 100, 540, 330), right, fontsize=10)

    top, row_h = 360, 22
    col_x = [72, 232, 392, 540]
    for r, row in enumerate(_TABLE_ROWS):
        y0 = top + r * row_h
        for c, cell in enumerate(row):
            page.insert_text((col_x[c] + 6, y0 + 15), cell, fontsize=10)
    for x in col_x:
        page.draw_line((x, top), (x, top + len(_TABLE_ROWS) * row_h))
    for r in range(len(_TABLE_ROWS) + 1):
        y = top + r * row_h
        page.draw_line((col_x[0], y), (col_x[-1], y))

    doc.save(path)
    doc.close()


def make_scanned_pdf(path: Path) -> None:
    """Image-only PDF: the text is rasterised, so there is no text layer to extract."""
    source = pymupdf.open()
    page = source.new_page(width=612, height=792)
    page.insert_text(
        (72, 120), "This page was scanned and has no text layer.", fontsize=14
    )
    page.insert_text(
        (72, 150), "A parser that reads text will find nothing here.", fontsize=14
    )
    pixmap = page.get_pixmap(dpi=100, colorspace=pymupdf.csGRAY)
    source.close()

    doc = pymupdf.open()
    scanned_page = doc.new_page(width=612, height=792)
    scanned_page.insert_image(
        scanned_page.rect, stream=pixmap.tobytes("jpg", jpg_quality=60)
    )
    doc.save(path)
    doc.close()


def make_short_text_pdf(path: Path) -> None:
    """Real text layer, but well under the 200-character minimum."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 120), "Short note: the deploy window is Friday.", fontsize=12)
    doc.save(path)
    doc.close()


def main() -> None:
    (FIXTURES / "nested_headings.md").write_text(NESTED_MARKDOWN, encoding="utf-8")
    (FIXTURES / "nav_footer.html").write_text(NAV_FOOTER_HTML, encoding="utf-8")
    make_two_column_table_pdf(FIXTURES / "two_column_table.pdf")
    make_scanned_pdf(FIXTURES / "scanned.pdf")
    make_short_text_pdf(FIXTURES / "short_text.pdf")
    print("wrote fixtures to", FIXTURES)


if __name__ == "__main__":
    main()
