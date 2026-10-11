# Nexus RAG

Multi-tenant document Q&A API (RAG). Backend only.

## Licence

This project uses `pymupdf4llm`, which depends on PyMuPDF licensed under AGPL-3.0. Anyone who
interacts with a modified version of this service over a network must be offered its source
code. See [ADR-0001](docs/decisions/0001-pdf-parser-agpl-licence.md) for the decision and its
revisit conditions.

## Evaluation (M8): measured results

All numbers come from `eval/runs/*` (committed) and are one run each on one corpus. Details,
hypotheses written before each run, and every caveat are in
[docs/decisions/eval-log.md](docs/decisions/eval-log.md). Free local stack only: BGE + BM25
via fastembed, bge-reranker-base, Ollama llama3.2:3b, on CPU.

**Dataset v1** (locked, sha256-pinned): 60 questions over a frozen 22-file corpus (473 chunks
at 350 tokens). Split once (seed 20261010) into **48 dev** (41 answerable, 7 unanswerable) and
**12 hold-out** (10 answerable, 2 unanswerable). Gold labels are text spans. Every choice was
made on dev; the hold-out was run once, at the end.

**Retrieval**: questions with full recall in the top k, plus MRR and nDCG@10 over the
answerable questions.

| run (dev unless noted) | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| E0 dense | 14/41 | 23/41 | 24/41 | 31/41 | 0.532 | 0.595 |
| E1 sparse (BM25) | 17/41 | 22/41 | 24/41 | 25/41 | 0.546 | 0.595 |
| E2 hybrid (RRF) | 17/41 | 28/41 | 30/41 | 34/41 | 0.628 | 0.692 |
| **E3 hybrid + rerank (chosen)** | 20/41 | 27/41 | 31/41 | 34/41 | 0.635 | 0.706 |
| E3 + expand=neighbors | 21/41 | 29/41 | 32/41 | 36/41 | 0.685 | 0.745 |
| E4 chunks 200 (E3 config) | 18/41 | 24/41 | 30/41 | 34/41 | 0.596 | 0.681 |
| E4 chunks 500 (E3 config) | 20/41 | 26/41 | 30/41 | 34/41 | 0.638 | 0.704 |
| **Hold-out, E3 (final, run once)** | 5/10 | 8/10 | 9/10 | 9/10 | 0.670 | 0.732 |

- **Final configuration** ([ADR-0012](docs/decisions/0012-final-retrieval-configuration.md)):
  hybrid, candidates 40, rerank on, expand none, chunks 350/50, chat limit 6.
  - **Rerank:** lifts paraphrase R@3 from 4/10 to 8/10 and drops multi-chunk MRR from 0.719
    to 0.401; the net effect is within noise. It costs about 38 s per query on this CPU
    (median, uncached), against 0.06 s without it.
  - **Neighbors off:** with them on, 23/48 questions would lose 1-2 sources to the
    2500-token context budget.
- **Noise:** one question is 2.4 points on dev and 10 points on the hold-out. The hold-out
  isn't worse than dev; that's all n = 10 can show.

**Answer generation** (E3 config, limit 6, all 48 dev questions, llama3.2:3b), by
deterministic checks:
- **Refusals (7 unanswerable):** 4/7 exact correct refusals; 2 near-refusals (a paraphrase
  of the refusal, not counted as correct); 1 missed. 1 false refusal on 41 answerable.
- **Citations:** 40 valid and 0 invalid numeric citations; 6/40 answers uncited; 15/40 cite
  a source containing a gold span. 4 answers have malformed citations (`[pymupdf4llm]`,
  `[M6]`, `[X-Accel-Buffering: no]`, `[3]RIGHT-09`), which are now reported by the API.
- **Reference facts:** checkable in 23 answers, all found in 7, mean share 0.49. Known
  limitation: references can hold facts the question doesn't ask about.
- **Speed:** 0 errors; generation median 120 s per answer (max 230 s), first token median
  107 s.

**LLM judge: failed calibration, not used**
([ADR-0011](docs/decisions/0011-llm-judge-failed-calibration.md)). The one-call
llama3.2:3b judge was compared with 15 hand grades:
- correctness exact match 7/15, against 10/15 for always answering "2";
- faithfulness 8/15, against 10/15 for always answering "faithful";
- all 3 unanswerable questions scored 0, including 2 exact correct refusals;
- it never listed an unsupported claim.

**Hand grades** (one person, 15 dev answers, **n = 15**): correctness 0 / 1 / 2 =
1 / 4 / 10; faithful 10 yes / 5 no (a claim counts only if the source it cites contains it).
7/15 are fully correct and faithful.

**Bugs found along the way:**
- **Message order after a clock step** (found in M8 by a flaky `make test-int`, fixed in
  `76890d9`, ADR-0009): the WSL2/Docker clock stepped back about 0.65 s mid-turn. Messages
  ordered by wall-clock `created_at` came back answer-before-question, so a follow-up lost its
  history. `created_at` is now monotonic per conversation, under a row lock.
- **Missing `refund` in the rate-limit test stub** (found at the start of M8 by
  `make test-int`, fixed in `bdcf7f9`): 37 integration tests got a 500 on every 422 path. The
  bug was in the test harness, not the app.
- **JWT clock leeway** (found before M8, in integration tests at the M4 close, 2026-10-08;
  `5d46126`, ADR-0006): the same WSL clock steps (about 1.4 s backwards every ~30 s) made
  fresh tokens fail `iat` validation, an intermittent 401. Fixed with a 5 s leeway.
- **Found by the evaluation runs themselves:**
  - leftover `<answer>`, `</p>` and similar tags in answers, now stripped;
  - non-numeric and fused citations, now reported;
  - a fact check that ignored number words and counted `[2]` as the number 2;
  - a refusal check that missed paraphrased refusals;
  - a runner that couldn't measure `expand=neighbors`.
