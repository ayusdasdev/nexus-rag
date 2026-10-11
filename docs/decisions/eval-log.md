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

### E3 measured (2026-10-10, commit f145996, clean tree at start; eval/runs/E3-hybrid-rerank)

Wall-clock 28 min 50 s for 48 questions (estimate was ~31 min); rerank median 37.6 s per
search, max 52.0 s; peak RSS 3.3 GB.

| run | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| E2 hybrid | 0.451 (17/41) | 0.728 (28/41) | 0.776 (30/41) | 0.854 (34/41) | 0.628 | 0.692 |
| E3 hybrid + rerank | 0.500 (20/41) | 0.707 (27/41) | 0.780 (31/41) | 0.870 (34/41) | 0.635 | 0.706 |

Per type, fully covered at R@1 / R@3 / R@10, and MRR (E2 then E3):

| type | E2 | E3 |
|---|---|---|
| factoid (17) | 8 / 15 / 16, MRR 0.655 | 10 / 12 / 15, MRR 0.680 |
| paraphrase (10) | 2 / 4 / 6, MRR 0.325 | 4 / 8 / 8, MRR 0.550 |
| exact-token (7) | 6 / 7 / 7, MRR 0.905 | 6 / 6 / 7, MRR 0.881 |
| multi-chunk (7) | 1 / 2 / 5, MRR 0.719 | 0 / 1 / 4, MRR 0.401 |

First-hit rank, E2 to E3: 11 questions up, 12 down, 18 unchanged.
- Up: q007 3-2, q012 7-1, q016 2-1, q017 2-1, q022 3-1, q023 none-1, q024 none-3, q027 6-2,
  q028 4-3, q038 3-1, q046 5-3.
- Down: q003 1-2, q005 3-5, q006 2-none, q015 2-6, q021 3-5, q033 2-3, q034 1-6, q043 1-6,
  q044 1-2, q045 2-3, q047 1-3, q050 3-7 (and q050 lost one of its three spans from the top 10).

Hypotheses against measurement:
- Overall R@10 at least 34/41: **held** (34/41). R@1 above 17/41: **held** (20/41). MRR above
  0.628: held only nominally (0.635, +0.007), which is within noise.
- Paraphrase: predicted q024 recovered (**right**, rank 3), q031 recovered (**wrong**, still not
  in the top 10), q029 not recovered (**right**). q023, which I made no prediction for, went
  from missed to rank 1. Paraphrase R@10 predicted 7-8/10: **8/10**.
- Exact-token: R@10 7/7 (**held**), R@1 6/7 (**held**). But q034 (a CLI command) fell from
  rank 1 to 6, and q038 rose from 3 to 1.
- **Not predicted:** the reranker hurts multi-chunk (MRR 0.719 to 0.401, R@1 1 to 0, R@10
  5 to 4) and lowers factoid R@3 (15 to 12, q006 out of the top 10). The gain is concentrated
  in paraphrase; elsewhere rerank moves as many questions down as up. Hypothesis, untested:
  the cross-encoder favours chunks that answer the whole question in one place, which a
  question needing two chunks doesn't have.
- With 7-17 questions per type, per-type moves of 1-2 questions are not evidence by themselves;
  the paraphrase gain (+4 at R@3) and multi-chunk MRR drop are the largest effects measured.

## E3-gen: one generation run, E3 config, limit 6 (2026-10-10) - part 1, stopped at 21/48

Config: hybrid + rerank, candidates 40, limit 6, llama3.2:3b on CPU via Ollama, answer
deadline 420 s (Ollama read timeout 300 s). Files: eval/runs/E3-gen (partial_summary.json).

- **Stopped by your memory rule**: available memory fell to 1,438 MB at 21/48. Ollama's
  llama-server had grown to 6.4 GB RSS (the model loaded at 2.6 GB); the eval runner stayed at
  0.57 GB. Stopped with SIGINT; all 21 lines intact; Ollama stopped; memory back to 8.6 GB.
- **Wall clock vs work**: 12:09 to 14:20 wall-clock, but the answers' own timers add up to
  ~45 min. A ~85 min gap appeared before answer 13 with no answer running; my inference (not
  verified) is that the VM was paused, e.g. by host sleep.
- Rerank cache worked: rerank 0.0 s per question; generation p50 131 s, max 230 s.
- Done: 16 factoid + 5 paraphrase (ids sort by type). **Refusal accuracy is not measured**: none
  of the 7 unanswerables ran.

Deterministic checks on the 21 (measured):
- Errors 0; answered 21; refusals 0 (none expected among these).
- Citations: 19 valid, 0 invalid; 3 answers with no citation (q001, q015, q017); 10 of 21 cite a
  source that contains a gold span.
- Reference facts: 11 answers have a checkable fact; mean share 0.57, all facts found in 4.
  Limitation seen: q017's reference names a 503 the question didn't ask about, so a right
  answer scores 0.

Format problems (counted by pattern, then read by me):
- 16/21 answers start with a citation (`[2] According to ...`).
- Non-numeric brackets the citation parser ignores, so "0 invalid" undercounts: q005
  `[pymupdf4llm]`, q015 `[M6]`. Fused citation: q014 `[3]RIGHT-09`.
- q021 dumped a raw markdown table. (Corrected after the full run: it is a complete table of
  ~600 characters, not cut off; the earlier "cut mid-row, likely the 512-token cap" was wrong.)
- q022's raw output echoed prompt tags; strip_prompt_scaffolding removed them.

My own reading of correctness (rough, not the judge, not calibrated): 15 right, 4 partial
(q001 omits the two-year part, q006 lists 3 of 6 stages, q021 table dump, q027 right conclusion
from an unrelated quote), 2 wrong (q014 says the docs don't say; q024 gives a deletion reason
instead of re-processing).

### E3-gen completed: 27 more in three batches of 9 (2026-10-10, measured)

Your order: unanswerable, exact-token, multi-chunk first. `ollama stop` and memory checked
(8.2-8.6 GB available) before each batch; lowest during a batch 3.86 GB; no 5-minute answer,
no stall, no clock jump. Final call without --ids wrote summary.json (48/48, no duplicates).
Timings over all 48: generation p50 120 s, p95 194 s, max 230 s, 101 min in total; first token
p50 107 s; retrieval p50 0.1 s, max 4.8 s (rerank cached, max 15 ms).

| check | result |
|---|---|
| refusal accuracy, unanswerable (exact sentence) | **4/7** correct (q052, q056, q057, q059) |
| missed refusals | 3/7: q053 answered only "[6]"; q055 pasted an unrelated source, then "There is no mention of payment methods"; q058 "not explicitly stated ... but" + a quote |
| false refusals, answerable | 1/41: q061 (its gold wasn't retrieved in E3 either) |
| errors | 0/48 |
| numeric citations | 40 valid, 0 invalid (but see the brackets the check can't see) |
| answered without any citation | 6/40 (q001, q015, q017, q029, q034, q050) |
| answered, citing a source that holds a gold span | 15/40 |
| reference facts | 23 answers checkable; mean share 0.49; all facts found in 7 |

Per type (answered / citing gold / facts all-found of checkable):
factoid 16 of 17 answered (1 false refusal), 7 cite gold, 4/10; paraphrase 10/10, 3, 1/5;
exact-token 7/7, 1, 1/4; multi-chunk 7/7, 4, 1/4.

Check limitations seen in this run: the near-refusal flag caught 0, but q055 and q058 are
paraphrased refusals; the citation check doesn't see non-numeric brackets; the fact check
penalises reference facts the question didn't ask for (q017).

Format problems over all 48 (counted by pattern and read by me):
- Starts with a bracket: 31/48 answers (28 numeric citations, 3 non-numeric: q005, q015, q038).
- A citation and nothing else: q053 "[6]", q040 "[5]".
- Brackets the citation check can't see: q005 `[pymupdf4llm]`, q015 `[M6]`,
  q038 `[X-Accel-Buffering: no]`. Fused to a word: q014 `[3]RIGHT-09`.
- Tags left in the final answer (strip_prompt_scaffolding doesn't cover them): `<answer>...</answer>`
  in q034 and q049; `<nexus readings export ...>` wrapping in q041; an HTML `</p>` in q050;
  q033 quotes a heading with `<history>` in it. q022's echoed tags were in the raw text only.
- Raw source pasted instead of an answer: q021 (a markdown table), q055.
- No answer was truncated (all end cleanly; the longest is 793 characters).

My own reading of correctness for the 41 answerable (rough, not the judge, not calibrated):
**23 right, 9 partial, 8 wrong, 1 false refusal.**
- Wrong: q014, q024, q028, q031, q033, q040 (only "[5]"), q042 ("restricts" tools; they are
  pre-approved), q045.
- Partial: q001, q006, q021, q027, q029, q034, q046, q047, q049.
- Paraphrase is weakest (wrong: q024, q028, q031, q033), consistent with its retrieval.

## E3-gen re-scored with the corrected checks (no regeneration)

Date: 2026-10-10. Same 48 stored answers (`eval/runs/E3-gen/results.jsonl`, unchanged);
`eval/tools/rescore.py` wrote `rescore.json` next to them. No model was loaded.
Two re-scorings: **checks fixed** (stored final text, current checks: the effect of the check
fixes alone) and **+ recleaned** (the stored raw output re-run through the app's new
cleanup first).

| | old (summary.json) | checks fixed | + recleaned |
|---|---|---|---|
| correct refusals (of 7) | 4 | 4 | 4 |
| near-refusals (of 7) | not an outcome | 2 (q055, q058) | 2 |
| missed refusals (of 7) | 3 | 1 (q053 "[6]") | 1 |
| false refusals (of 41) | 1 (q061) | 1 | 1 |
| answers with malformed citations | not checked | 4 | 4 |
| numeric citations valid / invalid | 40 / 0 | 40 / 0 | 40 / 0 |
| answered without citation | 6 | 6 | 6 |
| answered citing gold | 15 | 15 | 15 |
| facts: checkable / all found / mean share | 23 / 7 / 0.49 | 23 / 7 / 0.49 | 23 / 7 / 0.49 |

- Malformed citations found: q005 `[pymupdf4llm]`, q014 `[3]RIGHT-09`, q015 `[M6]`,
  q038 `[X-Accel-Buffering: no]`: exactly the four I found by reading, and no others.
- Refusal wording inside an answer to an answerable question: 0 of 40.
- Per type, only unanswerable (near 0 → 2, missed 3 → 1) and the malformed counts
  (factoid 3, exact-token 1) changed.
- The fact check didn't move: it already ignored facts the question states (`c8480ae`,
  before the run).
- **Known limitation of the fact check (left as is, decided 2026-10-10):** it scores every
  number and identifier in the reference answer, including ones the question doesn't ask
  about. q017 asks what happens to *search* when Redis is down; the reference also says chat
  fails closed with 503, so a correct "search fails open" answer scores 0/1 on "503". Fixing
  it means per-question fact lists or a changed reference, which would be dataset v2, so v1
  keeps it and fact-share numbers on v1 carry this bias.
- Recleaning changed the final text of 4 answers: q034 and q049 lose `<answer>` wrappers,
  q050 loses `</p>`, q014 gets `[3] RIGHT-09`. q041's `<nexus readings export ...>` and q050's
  leading `<pymupdf4llm (...` are not tags and stay; q033's `<history>` is a backtick quote of
  a source and stays. None of the counts above depend on these text changes.
- The near-refusal pattern was written from the two cases it now catches (n = 2), so it is
  fitted to them; the tests add four other wordings and four negatives, but its precision on
  new answers is unmeasured.

## Judge calibration: llama3.2:3b one-call judge vs your 15 hand grades (E3-gen)

Date: 2026-10-11. `eval/tools/judge_run.py --run E3-gen`: the approved judge prompt
(unchanged), Ollama llama3.2:3b, temperature 0, on the stored answers of the fixed
20-question dev sample (nothing regenerated, no hold-out). Run 07:32:56-08:00:30 UTC
(27 min 34 s); calls 57-152 s (median ~78 s, the first includes model load); min available
memory 2,697 MB; no clock jump, no stall. 0 unreadable replies (0/20 errors).
Verdicts and raw replies: `eval/runs/E3-gen/judge.jsonl`; your grades:
`eval/calibration/E3-gen.grades.jsonl`; agreement: `eval/calibration/E3-gen.agreement.json`.

Your faithfulness rule: a claim is supported only if the source it cites contains it (a
right fact cited to the wrong number is "n"). The judge prompt instead asks whether each
claim is supported by *the sources* (any of them), so some faithfulness disagreement is
built in.

| agreement on your 15 | judge | always "2" | always "1" | always "faithful" |
|---|---|---|---|---|
| correctness exact | **7/15** | 10/15 | 4/15 | |
| correctness within 1 | **14/15** | 14/15 | 15/15 | |
| faithful | **8/15** | | | 10/15 |

- **The judge is worse than a constant grader.** Always answering "2" matches your
  correctness exactly 10/15 times (judge 7/15), and always answering "faithful" matches 10/15
  (judge 8/15). Within-1 (14/15) says nothing here: always answering "1" gets 15/15.
- Correctness confusion (yours -> judge): 2->1 ×6, 2->2 ×3, 1->1 ×4, 2->0 ×1, 0->1 ×1. It
  pulls toward 1: 14 of its 20 grades are 1.
- **Faithfulness: it caught 2 of your 5 "n"** (q044, q046) and missed 3 (q012, q024, q027).
  It said "n" on 4 you marked "y" (q008, q021, q034, q056).
- q012 is a confirmed wrong-source case: the quoted "Hold out ~20%" is in source [1] and
  the answer cites [2]. The judge rated it faithful. For q024, q027 and q044 the quoted text
  is in the cited source; your "n" there rests on other claims, which I didn't check.
- **It never gave a reason:** `unsupported_claims` is empty in all 20 replies, including all
  8 "faithful: false" verdicts, which contradicts its own prompt.
- **It fails on refusals:** q056 and q057 are exact correct refusals and q053 is a missed
  refusal ("[6]"), and it gave all three correctness 0 and faithful false. You graded q056 2/y.
  The deterministic refusal check gets these right.

Judge's own scores on all 20, **rough and uncalibrated** (and by the above, not reliable):
correctness 0: 3, 1: 14, 2: 3 (mean 1.00); faithful 12 true / 8 false. Answerable 17:
0: 0, 1: 14, 2: 3; faithful 12/5. Unanswerable 3: all 0, all unfaithful.

Conclusion (n = 15, one run, one prompt): this judge's correctness and faithfulness scores
carry less information than a constant, so they shouldn't be reported as a quality number.
Refusals should stay with the deterministic check. Anything that changes the judge (prompt,
a reason field, per-citation faithfulness, a bigger model, Anthropic) is your decision and
would need a new calibration against these same 15 grades.

### Decision (2026-10-11): the 3B judge failed calibration (ADR-0011)
The judge isn't changed, and its numbers aren't used anywhere as a quality measure. It failed
on four counts:
- correctness exact 7/15 vs 10/15 for always "2";
- faithfulness 8/15 vs 10/15 for always "faithful";
- all 3 unanswerables scored 0, including 2 exact correct refusals;
- no unsupported claims ever listed.

Headline answer-quality metrics are the deterministic checks plus your hand grades.

**Your hand grades of E3-gen, a small hand-measured sample (n = 15):**

| type | n | correctness 0 / 1 / 2 | faithful y / n |
|---|---|---|---|
| factoid | 6 | 0 / 1 / 5 | 5 / 1 |
| paraphrase | 4 | 1 / 0 / 3 | 2 / 2 |
| exact-token | 2 | 0 / 2 / 0 | 2 / 0 |
| multi-chunk | 2 | 0 / 1 / 1 | 0 / 2 |
| unanswerable | 1 | 0 / 0 / 1 | 1 / 0 |
| **all** | **15** | **1 / 4 / 10** | **10 / 5** |

- 7/15 are both fully correct (2) and faithful: q007, q008, q015, q018, q022, q030, q056.
- The 15 were drawn from the seeded judge sample, not chosen to be representative per type.
  Per-type counts of 1-6 are too small to compare types.
