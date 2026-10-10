# Retrieval observations (M4 4.7)

Date: 2026-10-08. HEAD `66a9478`. Qualitative notes from four queries on `sample_docs/`. These
are not metrics: five documents and four queries can't support a measured claim. The M8 eval
does that. Every note below cites the output it came from, pasted as printed.

## Setup

- `make up`, `make migrate`, Celery worker (concurrency 1) and uvicorn (no reload) on :8000.
- New tenant via `POST /v1/auth/signup`, then each file in `sample_docs/` uploaded through
  `POST /v1/documents`. Result: 01-05 `ready`; `06_scanned.pdf` `failed` with
  `No extractable text: the file is scanned, image-only, or nearly empty.`, as EXPECTED.md says.
  The tenant holds 29 chunks: 01_text 14, 02_table 1, 03_2col 2, 04_html 5, 05_readme 7.
- Each query was sent as `POST /v1/search` with `{"limit": 5, "debug": true}` plus:
  dense = `mode=dense, rerank=false`; sparse = `mode=sparse, rerank=false`;
  hybrid = `mode=hybrid, rerank=false`; hybrid+rerank = `mode=hybrid, rerank=true`.
  `candidates` was left at the default (40) and `expand` at `none`.
- Labels are `<document>#<chunk_index>`. `trace.*` lines show the top 5 of each debug list with
  that stage's own score: cosine for dense, BM25 for sparse, RRF for fused, cross-encoder logit
  for rerank. The `score` on each item is the final stage's score. Some repeated trace lines
  are left out; every line shown is verbatim.

## Q1: exact term, `WID-0042`

The token occurs only in `04_html#2` (the `nexus-cli devices calibrate --device WID-0042` block).

```
-- dense
   1. 04_html#2    score=0.0164  Calibrating widgets > Temperature offsets > Using the calibration command
   2. 03_2col#0    score=0.0161  None
   3. 01_text#2    score=0.0159  Nexus Widgets Deployment Guide > 3. Installing hardware > 3.1 Mounting widgets
   4. 05_readme#6  score=0.0156  Nexus Widgets > License
   5. 01_text#8    score=0.0154  Nexus Widgets Deployment Guide > 7. Maintenance
   trace.dense: 04_html#2(0.595), 03_2col#0(0.529), 01_text#2(0.527), 05_readme#6(0.520), 01_text#8(0.519)
-- sparse
   1. 04_html#2    score=0.0164  Calibrating widgets > Temperature offsets > Using the calibration command
   trace.sparse: 04_html#2(12.984)
-- hybrid
   1. 04_html#2    score=0.0328  Calibrating widgets > Temperature offsets > Using the calibration command
   2. 03_2col#0    score=0.0161  None
   3. 01_text#2    score=0.0159  Nexus Widgets Deployment Guide > 3. Installing hardware > 3.1 Mounting widgets
   4. 05_readme#6  score=0.0156  Nexus Widgets > License
   5. 01_text#8    score=0.0154  Nexus Widgets Deployment Guide > 7. Maintenance
-- hybrid+rerank
   1. 04_html#2    score=2.2480  Calibrating widgets > Temperature offsets > Using the calibration command
   2. 05_readme#6  score=-5.3343  Nexus Widgets > License
   3. 05_readme#2  score=-5.7204  Nexus Widgets > Getting started > Requirements
   4. 01_text#11   score=-6.0247  Nexus Widgets Deployment Guide > 10. Glossary
   5. 01_text#4    score=-6.7366  Nexus Widgets Deployment Guide > 4. Calibration
   trace.rerank: 04_html#2(2.248), 05_readme#6(-5.334), 05_readme#2(-5.720), 01_text#11(-6.025), 01_text#4(-6.737)
```

- **All four modes put the right chunk first.**
- **Dense** got it right, but by a thin margin: cosine 0.595 against 0.529 for an unrelated
  chunk. Ranks 2-5 are noise with almost identical cosines (0.519-0.529), so dense sees nothing
  special about the token.
- **Sparse** returned exactly one result, the right one. BM25 only returns chunks that share a
  term with the query, so it has nothing to say for the other four slots. That's correct here,
  and it shows sparse can come back short.
- **Hybrid** is dense's list with the matching chunk's RRF score doubled (0.0328). Ranks 2-5
  are dense's noise.
- **Rerank** separated the hit clearly (logit 2.25, the next one -5.33). Its ranks 2-5 differ
  from dense's but are still unrelated.

## Q2: near-paraphrase, `my notifications keep going off whenever someone opens the fridge door`

Target: `01_text#6` (5.2 Choosing durations: "A duration of thirty seconds will fire on a door
opening and closing"). This query still shares "door" with the target, so it isn't a clean
paraphrase. Q3 is.

```
-- dense
   1. 01_text#6    score=0.0164  Nexus Widgets Deployment Guide > 5. Alerts > 5.2 Choosing durations
   2. 01_text#5    score=0.0161  Nexus Widgets Deployment Guide > 5. Alerts > 5.1 Writing rules
   3. 03_2col#1    score=0.0159  None
   4. 01_text#2    score=0.0156  Nexus Widgets Deployment Guide > 3. Installing hardware > 3.1 Mounting widgets
   5. 01_text#0    score=0.0154  Nexus Widgets Deployment Guide > 1. Introduction
   trace.dense: 01_text#6(0.561), 01_text#5(0.527), 03_2col#1(0.493), 01_text#2(0.490), 01_text#0(0.489)
-- sparse
   1. 01_text#6    score=0.0164  Nexus Widgets Deployment Guide > 5. Alerts > 5.2 Choosing durations
   2. 03_2col#0    score=0.0161  None
   3. 01_text#12   score=0.0159  Nexus Widgets Deployment Guide > 11. Frequently asked questions
   4. 03_2col#1    score=0.0156  None
   5. 01_text#5    score=0.0154  Nexus Widgets Deployment Guide > 5. Alerts > 5.1 Writing rules
   trace.sparse: 01_text#6(14.175), 03_2col#0(7.517), 01_text#12(5.993), 03_2col#1(5.069), 01_text#5(3.397)
-- hybrid
   1. 01_text#6    score=0.0328  Nexus Widgets Deployment Guide > 5. Alerts > 5.2 Choosing durations
   2. 01_text#5    score=0.0315  Nexus Widgets Deployment Guide > 5. Alerts > 5.1 Writing rules
   3. 03_2col#1    score=0.0315  None
   4. 03_2col#0    score=0.0311  None
   5. 01_text#12   score=0.0304  Nexus Widgets Deployment Guide > 11. Frequently asked questions
-- hybrid+rerank
   1. 01_text#6    score=-0.7566  Nexus Widgets Deployment Guide > 5. Alerts > 5.2 Choosing durations
   2. 03_2col#0    score=-5.7607  None
   3. 03_2col#1    score=-5.7977  None
   4. 01_text#5    score=-7.6111  Nexus Widgets Deployment Guide > 5. Alerts > 5.1 Writing rules
   5. 04_html#1    score=-7.7890  Calibrating widgets > Temperature offsets
   trace.rerank: 01_text#6(-0.757), 03_2col#0(-5.761), 03_2col#1(-5.798), 01_text#5(-7.611), 04_html#1(-7.789)
```

- **All four modes put the right chunk first.**
- **Sparse** does well here because of the shared word "door" (BM25 14.2, the next one 7.5).
- **Dense** puts the sibling section 5.1 Writing rules second. That's a reasonable neighbor for
  an alerts question.
- **Rerank** gives the top hit a negative logit (-0.76) but still a wide gap to rank 2 (-5.76).
  The logits aren't calibrated, so a fixed "relevant if > 0" threshold would have dropped the
  correct answer. That's worth remembering for the M5 empty-retrieval refusal.

## Q3: strict paraphrase, `for how long is historical sensor information stored before it is thrown away`

Target: `01_text#9` (8. Data retention: "Readings are kept for ninety days at full resolution and
for two years as hourly averages"). The query shares no content word with that chunk.

```
-- dense
   1. 01_text#9    score=0.0164  Nexus Widgets Deployment Guide > 8. Data retention
   2. 01_text#8    score=0.0161  Nexus Widgets Deployment Guide > 7. Maintenance
   3. 03_2col#1    score=0.0159  None
   4. 01_text#4    score=0.0156  Nexus Widgets Deployment Guide > 4. Calibration
   5. 01_text#12   score=0.0154  Nexus Widgets Deployment Guide > 11. Frequently asked questions
   trace.dense: 01_text#9(0.731), 01_text#8(0.614), 03_2col#1(0.607), 01_text#4(0.600), 01_text#12(0.579)
-- sparse
   1. 03_2col#0    score=0.0164  None
   2. 01_text#11   score=0.0161  Nexus Widgets Deployment Guide > 10. Glossary
   3. 01_text#4    score=0.0159  Nexus Widgets Deployment Guide > 4. Calibration
   4. 01_text#12   score=0.0156  Nexus Widgets Deployment Guide > 11. Frequently asked questions
   5. 01_text#8    score=0.0154  Nexus Widgets Deployment Guide > 7. Maintenance
   trace.sparse: 03_2col#0(7.667), 01_text#11(6.764), 01_text#4(6.445), 01_text#12(4.982), 01_text#8(3.336)
-- hybrid
   1. 01_text#8    score=0.0315  Nexus Widgets Deployment Guide > 7. Maintenance
   2. 01_text#4    score=0.0315  Nexus Widgets Deployment Guide > 4. Calibration
   3. 01_text#12   score=0.0310  Nexus Widgets Deployment Guide > 11. Frequently asked questions
   4. 03_2col#0    score=0.0303  None
   5. 01_text#11   score=0.0295  Nexus Widgets Deployment Guide > 10. Glossary
   trace.fused: 01_text#8(0.032), 01_text#4(0.031), 01_text#12(0.031), 03_2col#0(0.030), 01_text#11(0.029)
-- hybrid+rerank
   1. 01_text#4    score=-2.4774  Nexus Widgets Deployment Guide > 4. Calibration
   2. 01_text#9    score=-2.5963  Nexus Widgets Deployment Guide > 8. Data retention
   3. 01_text#8    score=-2.6806  Nexus Widgets Deployment Guide > 7. Maintenance
   4. 01_text#6    score=-3.8938  Nexus Widgets Deployment Guide > 5. Alerts > 5.2 Choosing durations
   5. 03_2col#1    score=-4.0702  None
   trace.rerank: 01_text#4(-2.477), 01_text#9(-2.596), 01_text#8(-2.681), 01_text#6(-3.894), 03_2col#1(-4.070)
```

Where `01_text#9` sits in each list (`limit=50`, hybrid):

```
rerank=False
  dense: len=29 01_text#9 -> rank 1 score 0.7313
  sparse: len=8 01_text#9 -> ABSENT
  fused: len=29 01_text#9 -> rank 9 score 0.0164
rerank=True
  fused: len=29 01_text#9 -> rank 9 score 0.0164
  rerank: len=29 01_text#9 -> rank 2 score -2.5963
```

- **Dense** got it right, and by the clearest margin of any query (0.731, the next one 0.614).
- **Sparse** got it wrong. It never matches the target and returns 8 chunks that share
  incidental words. Of the query's words, only "sensor(s)", "before", "long", "away" and
  "stored" occur anywhere in the corpus, and none of them in the target chunk.
- **Hybrid without rerank got it wrong, and worse than dense alone.** Dense's rank-1 chunk
  falls to fused rank 9. The mechanism: `CANDIDATES=40` is more than the tenant's 29 chunks, so
  dense returns every chunk, and each of sparse's 8 matches collects two RRF terms (about
  1/61 + 1/65). A chunk that only dense finds gets one term (1/61 = 0.0164) even at rank 1.
  On this corpus, hybrid acts like "sparse matches first, ordered by dense".
- **Rerank** recovered the target to rank 2, behind 4. Calibration. The logits are close
  (-2.48, -2.60, -2.68), so it isn't confident about any of them.
- **Hypothesis for M8 (not a conclusion):** plain hybrid may hurt paraphrased questions when
  the sparse list is short and the dense list covers the whole tenant. Two things to measure on
  the real corpus: whether this survives when the corpus is much larger than `CANDIDATES`, and
  whether weighted RRF or a dense-only fallback for short sparse lists helps (E1/E2).

## Q4: numeric, two documents, `how much does the plan with one hundred devices cost per month`

The answer (Growth, 249 USD, 100 widgets) is in `02_table#0` and in `05_readme#5`.

```
-- dense
   1. 02_table#0   score=0.0164  Pricing and specifications
   2. 05_readme#5  score=0.0161  Nexus Widgets > Plans
   trace.dense: 02_table#0(0.735), 05_readme#5(0.664), 03_2col#0(0.529), 05_readme#1(0.519), 05_readme#3(0.511)
-- sparse
   1. 02_table#0   score=0.0164  Pricing and specifications
   2. 01_text#4    score=0.0161  Nexus Widgets Deployment Guide > 4. Calibration
   trace.sparse: 02_table#0(14.028), 01_text#4(5.880), 01_text#10(5.113), 01_text#13(4.979), 01_text#3(4.757)
-- hybrid
   1. 02_table#0   score=0.0328  Pricing and specifications
   2. 01_text#13   score=0.0308  Nexus Widgets Deployment Guide > 12. API and troubleshooting
   3. 03_2col#0    score=0.0302  None
   4. 05_readme#5  score=0.0300  Nexus Widgets > Plans
-- hybrid+rerank
   1. 02_table#0   score=-5.3000  Pricing and specifications
   2. 05_readme#5  score=-5.5906  Nexus Widgets > Plans
   3. 03_2col#0    score=-8.0608  None
```

(Lists trimmed to the ranks discussed; the lines shown are verbatim.)

- **Every mode ranks the pricing table first**, so each one finds the answer.
- **Dense and hybrid+rerank** put the second source (`05_readme#5`) at rank 2.
- **Sparse** misses `05_readme#5` from its top 5. That chunk writes the numbers as digits
  ("100"), and the query spells them out ("one hundred").
- **Hybrid** pushes it to rank 4, behind `01_text#13`, which comes in through sparse with a
  2-list RRF bonus. This is the same pattern as Q3, milder.

## Neighbor expansion check

`{"query": "WID-0042", "limit": 1, "debug": true, "expand": "neighbors"}`:

```
hit 2 Calibrating widgets > Temperature offsets > Using the calibration command
  neighbor 1
  neighbor 3
stages: ['embed_query', 'dense_search', 'sparse_search', 'fuse', 'rerank', 'expand']
```

The hit at index 2 got indexes 1 and 3 of the same document, and the trace shows the `expand`
stage. The command block alone ("The same step can be run from the command line") doesn't say
which step. Neighbor 1 ("Place a reference thermometer...") supplies it, which is the case
expansion is meant for.

## Side observations

- In `dense` or `sparse` mode, the item `score` is the single-list RRF value (1/(60+rank)), not
  the cosine or BM25 score. Only the trace shows the raw score. That's harmless, but callers
  shouldn't compare scores across modes.
- `03_2col` chunks have `heading_path` null. That's correct (the document has no headings, and
  the running header was correctly kept out), but those chunks carry no section context for
  the reranker or the prompt.
- `02_table#0` keeps bold markers in the table header (`|**Plan**|**Monthly price**|...`).
  EXPECTED.md forbids `**` only in `01_text_heavy.pdf`, so this isn't a regression, but it adds
  noise tokens to the chunk.
- The first query after API start spent 1131 ms in `embed_query` (lazy model load). Later
  queries spent 23 ms there.
