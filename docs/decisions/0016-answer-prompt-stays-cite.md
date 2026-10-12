# ADR-0016: The answer prompt stays `cite`; quote styles kept as settings

Date: 2026-10-12
Status: accepted

## Context
The M8 failure analysis made context use the largest failure bucket (14 of 26): answers
that cite a non-gold source, or none, while the gold chunk is in the prompt. M10 tried two
answer prompts that make the model quote the answering sentence before answering, both
behind `ANSWER_STYLE`. Each had its hypothesis and decision rule committed before a
~100-minute dev run. The models were llama3.2:3b on CPU, and nothing ran on Anthropic.

| dev (41 answerable, 7 unanswerable) | `cite` (E3-gen) | `quote_then_cite` | `quote_refusal_first` |
|---|---|---|---|
| exact correct refusals | 4/7 | 0/7 | 5/7 |
| false refusals | 1 | 0 | 2 |
| answers citing a gold source | 15/40 | 21/41 | 18/39 |
| uncited / malformed | 6 / 4 | 0 / 0 | 0 / 0 |
| answers following the Quote:/Answer: form | n/a | 41/41 | 13/39 |

The details are in `eval-log.md` (M10-2, M10-3).

## Decision
`ANSWER_STYLE` keeps its default, `cite` (`app/prompts/rag_system.md`, the M5 prompt).
`quote_then_cite` and `quote_refusal_first` stay in the code as settings for future runs.
Neither is the default:
- `quote_then_cite` broke exact refusals (0/7), because a Quote: line is always written;
- `quote_refusal_first` restored refusals but answered with a bare quote two times out of
  three, and failed the user's rule on false refusals (2 > 1) and on gold citations
  (18 < 20).

ADR-0007's rules are word for word the same in all three prompts (tested), so the safety
properties don't depend on the style.

## Alternatives considered
- **Adopt `quote_then_cite` and fix refusals in code**, by stripping a leading Quote: before
  the exact refusal check. It was rejected because it rescues a prompt result with
  post-processing the decision rule didn't include. It would also hide the missed refusals
  where an irrelevant quote is used as an answer (q055).
- **Adopt `quote_refusal_first` on its better refusals.** It fails two of four conditions,
  and bare-quote answers are worse for a reader.
- **Rerun to see if the margins move.** Rejected: rerunning until a variant passes is
  selection on noise, and dev has already been used for every choice. A real check would
  need a fresh labelled set (dataset v2) and is deferred, as no default changed.
- **A stronger model** (Anthropic, or a larger local model). The 3B model's instruction
  following is the limit both variants hit. It's out of scope for the free setup, and the
  provider Protocol makes it a configuration change later.

## Consequences
- The shipped answer behaviour is exactly the M5/M8-measured one, so E3-gen remains the
  baseline and the README numbers stay valid.
- Grounding (gold citations 15/40, uncited 6) is still the known weak spot. The evidence says
  quoting helps grounding with this model, but it costs refusal reliability, which matters
  more for this API.
- Two extra prompt files are kept, with tests, so maintenance is small. They can be rerun
  with `--set answer_style=...`.
- Dataset v2 stays deferred.
