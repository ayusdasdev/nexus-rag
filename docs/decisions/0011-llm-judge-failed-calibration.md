# ADR-0011: The 3B LLM judge failed calibration; answer quality is measured without it (M8)

Date: 2026-10-11
Status: accepted

## Context
M8 (guide 8.4) planned a one-call LLM judge: correctness 0/1/2 and faithfulness, on a fixed
20-question dev sample, calibrated against hand grades before use. With the free setup the
judge is llama3.2:3b on Ollama (`eval/judge.py`, prompts in `eval/prompts/`). You hand-graded
15 of the 20 E3-gen answers (`eval/calibration/E3-gen.grades.jsonl`). Your faithfulness rule
was stricter than the prompt: a claim counts only if the source it *cites* contains it.

The judge ran once on the stored answers (2026-10-11, 0/20 unreadable replies). Against your
15 grades (`eval/calibration/E3-gen.agreement.json`):

| | judge | constant baseline |
|---|---|---|
| correctness exact | 7/15 | 10/15 (always "2") |
| correctness within 1 | 14/15 | 15/15 (always "1") |
| faithfulness | 8/15 | 10/15 (always "faithful") |

- It scored all 3 unanswerable questions in the sample 0 and unfaithful, including 2 exact
  correct refusals (q056, q057).
- It never listed an unsupported claim, in any of its 20 replies, including its 8
  "faithful: false" verdicts.
- It caught 2 of your 5 unfaithful answers and missed the confirmed wrong-source citation
  (q012).

## Decision
- The judge is not changed, and its scores are not used anywhere as a quality measure:
  not in summaries, ADRs, the README or interview material. The code, the prompts and the
  run's files stay, as the record of the failed calibration.
- The headline answer-quality metrics are:
  - **the deterministic checks**, on every answer: refusal outcome by the exact refusal
    sentence (correct, near and missed refusals, false refusals), numeric citation validity
    and malformed citations, citing a gold-span source, and the reference-fact check (with
    its known q017-type limitation);
  - **your 15 hand grades**, reported as a small hand-measured sample, always with n = 15.

## Alternatives considered
- Tune the prompt (a reason field, per-citation faithfulness) and re-calibrate: possible
  later, but each change needs a new calibration against the same 15 grades. Not chosen now.
- A bigger local model as judge: more memory and time on this CPU-only machine; not tried.
- An Anthropic judge: needs a key and your approval; not used (free setup only).
- Use the judge anyway, with a caveat: rejected. Its scores carry less information than a
  constant, so any caveat would understate the problem.

## Consequences
- There is no automatic correctness score beyond the deterministic checks. Correctness on
  new runs needs either new hand grades or a judge that passes calibration.
- A future judge must beat the constant baselines above on these same 15 grades before its
  numbers are reported, and it must handle refusals at least as well as the exact check.
- n = 15 is small: one grade moves a rate by about 7 points.
