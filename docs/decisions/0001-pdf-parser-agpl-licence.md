# ADR-0001: Use pymupdf4llm (AGPL-3.0) for PDF parsing

Date: 2026-10-04
Status: accepted

## Context
Milestone 2 ingests PDFs into heading-aware chunks. `pymupdf4llm` produces Markdown with
`#`-level headings, which the heading split depends on. It depends on PyMuPDF, which is
licensed under AGPL-3.0 or sold under a commercial licence.

## Decision
Use `pymupdf4llm` (and therefore PyMuPDF) under AGPL-3.0. No commercial licence is purchased.

## Alternatives considered
- Buy a commercial PyMuPDF licence: rejected, this is a personal portfolio project.
- A permissively licensed parser such as `pypdf`: viable, but heading detection from font size
  is weaker, so the heading split would be less reliable.

## Consequences
- AGPL-3.0 section 13 applies when the software is offered to users over a network. Anyone
  interacting with a modified version of this service must be offered its source. Because this
  project is not distributed as a commercial hosted service, this is accepted as-is.
- Revisit this decision if the project becomes a commercial hosted service or if source
  disclosure of this codebase becomes unacceptable.
