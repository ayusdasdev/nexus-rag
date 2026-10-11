# ADR-0012: Final retrieval configuration for v1 (M8)

Date: 2026-10-11
Status: accepted

## Context
M8 ran E0-E4 and E3-neighbors on the dev split of dataset v1 (48 questions: 41 answerable,
7 unanswerable), retrieval only, measured as recall@k (questions with full recall), MRR and
nDCG@10 (`docs/decisions/eval-log.md`). The hold-out (12 questions) was not used to choose
anything. You chose the configuration from the dev numbers below.

| dev, 41 answerable | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 | retrieval per query (median, CPU) |
|---|---|---|---|---|---|---|---|
| E2 hybrid, no rerank | 17 | 28 | 30 | 34 | 0.628 | 0.692 | 0.06 s |
| **E3 hybrid + rerank (chosen)** | 20 | 27 | 31 | 34 | 0.635 | 0.706 | 37.7 s (uncached) |
| E3 + expand=neighbors | 21 | 29 | 32 | 36 | 0.685 | 0.745 | (rerank cached) |
| E4 chunks 200 (E3 config) | 18 | 24 | 30 | 34 | 0.596 | 0.681 | n/a (partly cached) |
| E4 chunks 500 (E3 config) | 20 | 26 | 30 | 34 | 0.638 | 0.704 | n/a (partly cached) |

## Decision
Retrieval for `/v1/chat` and conversations: **hybrid (BGE dense + BM25, RRF), candidates 40,
rerank on (bge-reranker-base), expand none, chunks 350 tokens with 50 overlap, chat limit 6.**
These are already the app's defaults; no setting changes.

- **Rerank on.** It changes which questions succeed more than how many:
  - paraphrase R@3 rises from 4/10 to 8/10 (E2 -> E3), the largest single effect measured;
  - multi-chunk MRR falls from 0.719 to 0.401, because the cross-encoder prefers one chunk
    that answers the whole question;
  - overall, R@1 17 -> 20, R@3 28 -> 27, R@10 34 -> 34, MRR 0.628 -> 0.635. The net effect
    is within noise on 41 questions (one question is 2.4 points).

  You chose paraphrase recall over latency.
- **Chunks 350/50.** 200 loses early ranks (R@3 27 -> 24, MRR 0.635 -> 0.596), 7 of its
  8 down-moves in paraphrase and multi-chunk. 500 ties 350 within noise and never beats it
  at any k, even though a larger chunk is an easier recall target.
- **Expand none.** Neighbors raise R@10 34 -> 36 and MRR 0.635 -> 0.685 (3 questions moved,
  all up), but each source becomes ~2.4x longer (median 172 -> 425 tokens). Packed into the
  2500-token context budget, 23/48 questions would lose 1-2 of their 6 sources. Answer
  quality with longer sources is unmeasured.

## Alternatives considered
- **Rerank off (E2):** about 600x faster retrieval on this CPU with the same R@10 and a
  similar MRR, but it loses the paraphrase R@3 gain. This is what I recommended; you
  preferred paraphrase recall.
- **Rerank fewer candidates** (to cut its latency): not tested; skipped by your decision.
- **Expand=neighbors on:** better retrieval numbers but an unmeasured cost to answers.
  Revisit only after a generation comparison on dev.
- **Chunk size 200 or 500:** see the decision.

## Consequences
- **Latency:** retrieval costs about 38 s per query on this CPU before generation starts
  (generation median ~120 s with llama3.2:3b), so a chat answer takes about 2.5-3 min here.
  A GPU, or a smaller candidate count for the reranker, is the lever if that matters.
- **Multi-chunk:** questions remain the weakest type (MRR 0.401 on dev). Parent-child chunking
  (E9) or neighbors are the candidates for later.
- **Hold-out:** run once with exactly this configuration. Its numbers are final and nothing is
  tuned on them.
- **Scope:** every number above is one run on one corpus. Differences of 1-2 questions are
  noise.
