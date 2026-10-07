# Expected results for sample_docs/

Regenerate with `make sample-docs`. The output is deterministic: the same command produces
byte-identical files. The content is fictional ("Nexus Widgets").

Each entry says what a correct parse or chunk looks like, and what a parsing problem looks
like. Marker strings are the reliable checks, because they are unique to this corpus.

Observations below were recorded by running the parser on the files as generated. Chunk counts
use the BGE tokenizer with `max_tokens=350, overlap=50`.

---

## 01_text_heavy.pdf (4 pages, PDF)

Title and H1/H2/H3 headings, long paragraphs. Section 4 (Calibration) is long enough to need
several chunks.

**Correct**
- Title: `Nexus Widgets Deployment Guide`.
- Heading text has no bold markers: `# Nexus Widgets Deployment Guide`, `## 1. Introduction`.
  The text `**` must not appear anywhere in the chunks.
- Headings appear in order: 1 Introduction, 2 Planning, 3 Installing (3.1, 3.2), 4 Calibration,
  5 Alerts (5.1, 5.2), 6 Network and security, 7 Maintenance, 8 Data retention, 9 Roles,
  10 Glossary, 11 FAQ, 12 API and troubleshooting.
- The Calibration section spans several chunks, each with `heading_path` starting with
  `Nexus Widgets Deployment Guide > 4. Calibration`.
- Largest chunk is 350 content tokens or fewer. Observed: 14 chunks, largest 332 with specials.

**Parsing problem looks like**
- Missing sections, or body text under the wrong heading. Text from one section appearing in
  another section's chunks.

---

## 02_table.pdf (1 page, PDF)

A pricing table with 4 plans and 4 columns, followed by a paragraph.

**Correct**
- The table comes out as one Markdown table with a header row and four data rows, every cell
  intact:
  `|Starter|19 USD|5|Email, 2 business days|`
  `|Team|79 USD|25|Email and chat, 1 business day|`
  `|Growth|249 USD|100|Priority chat, 4 hours|`
  `|Enterprise|Custom|Unlimited|Dedicated engineer, 1 hour|`
- The paragraph after the table appears after the table, not inside it. It mentions
  `Growth and Enterprise plans add the export endpoint`.
- A table row is never split across two chunks.

**Parsing problem looks like**
- A cell broken mid-word, with a stray pipe: `Email, 2 business da|ys`. This happened when the
  generator's columns were too narrow, so the test is a good regression check.
- Rows merged, or a missing row.

---

## 03_two_column.pdf (2 pages, PDF)

3 pages. Two columns per page. Left column sentences are numbered `LEFT-01` to `LEFT-12`, right
column `RIGHT-01` to `RIGHT-12`, both on page 1. Every page has the running header
`NEXUS-RUNNING-HEADER` and the footer `NEXUS-CONFIDENTIAL-FOOTER Page N of 3`. Pages 2 and 3
contain unnumbered filler text.

**Correct**
- All `LEFT-01`..`LEFT-12` appear before `RIGHT-01` on page 1, in order. Columns are not
  interleaved.
- `NEXUS-RUNNING-HEADER` and `NEXUS-CONFIDENTIAL-FOOTER` must NOT appear in any chunk text, and
  must NOT appear in any `heading_path`. The header is removed from the top of every page, and
  the footer is removed by the parser.
- No `heading_path` contains `NEXUS-` at all.

**Parsing problem looks like**
- `LEFT-` and `RIGHT-` sentences interleaved line by line, which means the columns were read
  in the wrong order.
- Any `LEFT-` or `RIGHT-` marker missing.
- `NEXUS-RUNNING-HEADER` or `NEXUS-CONFIDENTIAL-FOOTER` in chunk text or heading paths. The header
  becoming a heading is the typical failure: every chunk on that page inherits it as its path.

---

## 04_docs_page.html (HTML)

A docs-site page with a cookie banner, a navigation bar, a sidebar, an article with H1/H2/H3
headings, a code block, a list, and a footer.

**Correct**
- The article is kept: `Calibrating widgets` as the root heading, with `Temperature offsets`,
  `Using the calibration command`, `Humidity offsets`, `Troubleshooting`, and
  `Offset looks wrong after moving a widget` as sub-headings.
- The code block is kept inside a fence or as code.
- Navigation and banner noise is dropped. These markers must NOT appear in the chunks:
  `NAV-MENU-ITEM`, `ACCEPT-ALL-COOKIES`, `FOOTER-LINKS`. The sidebar text ("In this guide") is
  also not expected.

**Parsing problem looks like**
- Any of `NAV-MENU-ITEM`, `ACCEPT-ALL-COOKIES`, `FOOTER-LINKS` appearing in chunk text.
  Those are boilerplate that extraction should have removed.
- Heading paths built from the sidebar instead of the article.

---

## 05_README.md (Markdown, read as plain text)

Three levels of nested headings, a bullet list, a Markdown table, and a fenced code block that
contains a blank line and a line beginning with `#`.

**Correct**
- The file is stored as-is. Headings nest as `Nexus Widgets > Getting started > Requirements`.
- The `Command line` section's code block stays intact, including the blank line and the comment
  `# Export the last day of readings as CSV.`. That comment is not a heading. The chunk for that
  block has `heading_path` `Nexus Widgets > Command line`.
- The Markdown table is one unit and is not split mid-row.

**Parsing problem looks like**
- A new heading path created from the `# Export the last day...` comment. That is a
  fenced-code bug.
- The code fence broken into two chunks at the blank line, leaving a dangling ` ``` ` in one of
  them.

---

## 06_scanned.pdf (image only, no text layer)

One page with a rendered image of text, and no text layer.

**Correct**
- Extraction raises `NoExtractableText`.
- The document is marked `failed` with an error starting with `No extractable text`. It is not
  retried.
- No chunks are created.

**Parsing problem looks like**
- The document is marked `chunked` with zero chunks.
- The document is retried. That is a transient-error bug, because scanned files are permanent.
