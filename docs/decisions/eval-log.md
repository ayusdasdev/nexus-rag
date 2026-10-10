# Eval log (M8)

One entry per experiment: hypothesis written **before** the run, then the measured result.
Dataset v1 (final, sha256-pinned), dev split only while tuning: 48 questions, of which 41
are answerable (factoid 17, paraphrase 10, exact-token 7, multi-chunk 7) and 7 unanswerable.
Retrieval metrics are over the 41 answerable ones. With n = 7-17 per type, one question moves
a per-type rate by 6-14 points: per-type differences of one or two questions are noise.

## E0-E2: retrieval mode, no rerank (written 2026-10-10, before running)

Config: candidates 40, limit 10, expand none, rerank off; only `mode` changes.

- **E0 dense only.** Hypothesis: strongest on paraphrase (the questions were reworded to share
  0-2 words with their span), weakest on exact-token (ids such as WID-0042, RIGHT-07 and CLI
  flags are rare strings a 384-d embedding blurs).
- **E1 sparse only (BM25).** Hypothesis: strongest on exact-token, and poor on paraphrase,
  where most questions share 0 content words with their span, so BM25 has little to match.
- **E2 hybrid (RRF).** Hypothesis: best overall Recall@10, since it unions both lists. From
  M4 4.7 (retrieval-observations.md): plain RRF may rank paraphrase hits *below* dense alone,
  because sparse noise pushes the dense rank-1 hit down; if so it shows as lower MRR/Recall@1
  on paraphrase in E2 than E0.

### E0-E2 measured (2026-10-10, commit 227e180, clean tree; files in eval/runs/E0-dense,
### E1-sparse, E2-hybrid)

Each run took 7-9 s wall-clock for 48 questions (p50 ~55 ms per search after the models load).
Recall@k is the mean share of gold spans in the top k; the count is questions fully covered.

| run | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| E0 dense | 0.378 (14/41) | 0.585 (23/41) | 0.630 (24/41) | 0.780 (31/41) | 0.532 | 0.595 |
| E1 sparse | 0.427 (17/41) | 0.569 (22/41) | 0.654 (24/41) | 0.687 (25/41) | 0.546 | 0.595 |
| E2 hybrid | 0.451 (17/41) | 0.728 (28/41) | 0.776 (30/41) | 0.854 (34/41) | 0.628 | 0.692 |

Recall@10 per type (fully covered / n):

| type | E0 dense | E1 sparse | E2 hybrid |
|---|---|---|---|
| factoid | 14/17 | 14/17 | 16/17 |
| paraphrase | 5/10 | 3/10 | 6/10 |
| exact-token | 7/7 | 7/7 | 7/7 |
| multi-chunk | 5/7 | 1/7 | 5/7 |

- E0/E1 hypotheses: supported in direction. Sparse is best on exact-token (R@1 7/7 vs dense
  5/7) and worst on paraphrase (3/10 at R@10). The exact-token gap is 2 questions of 7.
- E2 hypothesis (best overall R@10): supported, 34/41 vs 31/41 (dense), a 3-question gap.
- M4 4.7 hypothesis (RRF pushes paraphrase hits down): **mixed, not confirmed**. Hybrid ranks
  q022 (1 to 3) and q027 (3 to 6) lower than dense alone, but q030, q033 and q028 higher, and
  paraphrase MRR is 0.325 (E2) vs 0.275 (E0). With n = 10 this can't be told apart from noise.
- Paraphrase is the weak type in every mode: q024, q029 and q031 are missed by all three,
  q023 by sparse and hybrid. Hybrid also misses factoid q061.
- Multi-chunk R@1 is capped at 0.5 for two-span questions (one chunk can hold one span), so
  its R@1 is not comparable to the other types.
- Duplicated text: in 2-4 questions per run the first hit is in a non-gold document that
  quotes the same text (cli-demo.md, retrieval- and generation-observations.md; q001, q022,
  q044, q049). Span matching counts these as hits, by the dataset's definition.

## E3: hybrid + rerank (written 2026-10-10, before running)

Config: mode hybrid, rerank on (bge-reranker-base, at most 50 fused candidates scored),
candidates 40, limit 10, expand none. Only `rerank` differs from E2.

Mechanism: the cross-encoder reads question and chunk together, so it can see paraphrases
that neither BM25 nor the bi-encoder matched, but it only reorders the fused pool. A gold
chunk outside the top 50 fused candidates cannot be recovered.

- **Overall.** Hypothesis: Recall@10 at least E2's 34/41, and the largest gain at the top:
  MRR above E2's 0.628 and Recall@1 above 17/41.
- **Paraphrase misses (E2 had none of these in the top 10).** Predictions, low confidence:
  - q031 (fake source number): **recovered** into the top 10. "dropped" and "citation" are
    the concept the question describes in other words.
  - q024 (file vanishes after re-upload): **recovered**. The ADR-0004 chunk says almost
    exactly this, only with "re-processing" and "ready".
  - q029 (first M5 answer never arrived): **not recovered**. The gold chunk is one of many
    near-identical M5/M6 timing notes in generation-observations.md; the reranker is likely
    to prefer another of them.
  So: 2 of the 3 recovered; paraphrase Recall@10 7-8/10 (E2 6/10).
- **Exact-token.** Hypothesis: Recall@10 stays 7/7 (all were already in E2's top 10);
  Recall@1 stays at 6/7 or drops by one, since cross-encoders can underweight rare ids
  (WID-0042, RIGHT-07, flags) that BM25 ranked first.
- **Cost.** Estimate ~38 s per search (up to 50 pairs at ~0.77 s), ~31 min for 48 questions.
