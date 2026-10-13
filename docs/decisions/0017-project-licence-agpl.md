# ADR-0017: The project is licensed AGPL-3.0-or-later

Date: 2026-10-13
Status: accepted

## Context
The repo is about to be published on GitHub and had no LICENSE file: without one, nobody may
legally reuse the code. PDF parsing depends on `pymupdf4llm` and PyMuPDF, which are AGPL-3.0
(ADR-0001), so anyone who distributes the combined work, or offers it to users over a network,
is bound by the AGPL whatever licence this repo's own code carries.

## Decision
License the project under AGPL-3.0-or-later (your choice, 2026-10-13):
- `LICENSE` holds the unmodified licence text from https://www.gnu.org/licenses/agpl-3.0.txt
  (661 lines, 34,523 bytes, sha256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`);
- `pyproject.toml` declares `license = "AGPL-3.0-or-later"`;
- the README's Licence section states both.

## Alternatives considered
- MIT or Apache-2.0 for this repo's own code, with a note that the combined work is bound by
  AGPL through PyMuPDF: easier to reuse snippets from, but two licences to explain, and every
  deployable form of the service is AGPL anyway.
- No licence (all rights reserved): readable on GitHub but not reusable; not what a public
  portfolio repo is for.

## Consequences
- One licence covers the code and its PDF dependency, so there is no mixed-licence nuance to
  explain.
- Copyleft: anyone who modifies the service and offers it over a network must offer its source
  (AGPL section 13). Some employers avoid AGPL code, which matters only for reuse, not for
  reading the repo.
- Revisit together with ADR-0001: if PyMuPDF is replaced by a permissively licensed parser,
  a permissive licence becomes possible. Relicensing needs the agreement of every copyright
  holder, which is only the author while there are no outside contributions.
