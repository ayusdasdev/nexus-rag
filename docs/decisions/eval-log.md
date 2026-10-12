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

## E3-neighbors: E3 + expand=neighbors, retrieval only (hypothesis written before the run)

Date: 2026-10-11. Config: E3 (hybrid, rerank, candidates 40, limit 10) + `expand=neighbors`,
dev split (48), tag `E3-neighbors`. No generation.

**What is scored.** Before this, the runner scored only each hit's own chunk text, so
expansion couldn't change any number. From `feat(eval): score the expanded text` on, a hit's
scored text is `retrieval.expanded_text`: chunk -1, the hit, chunk +1, joined as the answer
model sees them (`chat._context` uses the same function). E0-E3 had expand=none, so their
numbers are unchanged.

**By construction:** expansion runs after ranking and only adds text, so the order of hits is
E3's and recall@k, MRR and nDCG@10 can't drop. Any change is a gold span found in a neighbor
(or across a chunk boundary). The cost isn't visible in these metrics: each hit gets longer,
so fewer hits fit the answer budget. I'll measure that as how many of the top 6 (chat's
limit) fit `max_context_tokens` 2500 when packed the way `build_messages` does
(approx_tokens = chars/4, best first, skipping one that doesn't fit; headings not counted,
because hits don't store them), for E3 and E3-neighbors.

**Hypothesis (yours):** helps multi-chunk and straddling answers; little effect elsewhere.

**My specific predictions:**
- multi-chunk (7): full recall@10 rises from 4/7 to at least 5/7, and MRR rises from 0.401.
- factoid, paraphrase, exact-token: at most +2 questions each at R@10; R@1 almost unchanged.
- Overall R@10 34/41 -> 35-37/41; nothing drops (guaranteed, see above).
- Budget: E3 fits ~6/6 of the top 6 in most questions; with neighbors, a median of 3-4 of 6
  fit, so a generation run would see fewer distinct sources.
- Time: 1-3 min (rerank cached, since expansion happens after it); a rerank stage over 1 s
  on any question means the cache missed, and I stop and tell you.

### E3-neighbors result (measured)
Run 2026-10-11 08:30:31-08:30:35 UTC (4 s; ~1 min estimated, rerank fully cached: max
rerank stage 11 ms), dev 48, clean tree (`07d5647`), min available memory 7,691 MB. Hit order
identical to E3 for all 48 questions (checked), as designed.

| 41 answerable | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| E3 | 20 | 27 | 31 | 34 | 0.635 | 0.706 |
| E3-neighbors | 21 | 29 | 32 | 36 | 0.685 | 0.745 |

| per type, full R@10 / MRR | E3 | E3-neighbors |
|---|---|---|
| factoid (17) | 15 / 0.680 | 16 / 0.739 |
| paraphrase (10) | 8 / 0.550 | 8 / 0.550 |
| exact-token (7) | 7 / 0.881 | 7 / 0.881 |
| multi-chunk (7) | 4 / 0.401 | 5 / 0.548 |

Only 3 questions moved, all up:
- q006 (factoid): missed in E3, found at rank 1;
- q046 (multi-chunk): first hit rank 3 -> 1, R@3 0.5 -> 1.0;
- q050 (multi-chunk): first hit 7 -> 2, R@10 0.67 -> 1.0.

Each is a gold span in a chunk next to a hit.

Predictions vs result:
- multi-chunk full R@10 >= 5/7 and MRR up: **held** (5/7, 0.401 -> 0.548).
- other types at most +2 at R@10, R@1 almost unchanged: **held** (factoid +1 at R@10 and
  R@1, paraphrase and exact-token unchanged).
- overall R@10 35-37/41: **held** (36/41). Nothing dropped (by construction).
- budget, median 3-4 of the top 6 fit: **wrong.** Tokens per hit rose from a median of 172
  to 425 (mean 176 -> 420), but a median of 6 of 6 still fit in 2500. All 6 fit in 25/48
  questions, 5 in 14 and 4 in 9 (E3: all 6 in 48/48). So 23/48 questions would lose 1-2
  sources in a generation run.
- time 1-3 min: faster than estimated (4 s).

Caveats:
- With expansion, a "hit" is a three-chunk window, a larger target than one chunk, so these
  numbers measure whether the answer model would *see* the span, not ranking precision.
- n = 3 questions moved, so the gain is small and the sample is small.
- Answer quality with ~2.4x longer sources on llama3.2:3b is unmeasured; no generation was
  run.

## E4: chunk-size sweep, 200 and 500 vs the 350 baseline (hypotheses written before any run)

Date: 2026-10-11. Retrieval only, dev split (48), E3 config (hybrid, rerank, candidates 40,
expand none, limit 10). Each size is a new eval tenant, ingested with
`CHUNK_MAX_TOKENS=200|500` and `CHUNK_OVERLAP_TOKENS=50`. The 350 tenant is unchanged, and
its E3 run is the baseline. Gold labels are text spans, not chunk ids, so the same labels
are valid for every size.

**Measured baseline (350):** 473 chunks, 74,423 tokens; per chunk min 7, median 132, max 350.
156 chunks are over 200 tokens and 51 are at 300 or more. Chunking is heading-bounded, so
most chunks are well under the cap.

**Read with care:** a bigger chunk is an easier recall target (more text that can contain a
span), and a smaller one a harder target. Recall differences between sizes are partly that,
not only ranking quality.

**Hypotheses:**
- **Guide:** a mid size (350) is best; small chunks lose context, large ones blur.
- **Chunk counts:** 200 splits roughly the 156 chunks over 200, so 620-720 chunks. 500 only
  changes sections longer than 350, so 430-460 chunks. Under ~40% of chunks change at 200,
  under ~15% at 500.
- **Overall R@10 (350: 34/41):** 200 gives 31-34; 500 gives 34-36, since it is the easier
  target and few chunks change. MRR (350: 0.635): 200 lower (0.55-0.62); 500 about the same
  (0.62-0.67).
- **Paraphrase** (350: R@3 8/10, R@10 8/10): 200 hurts. Less surrounding text gives the dense
  model and the reranker less to match a reworded question against: R@10 6-8/10. 500 is
  about the same (7-9/10).
- **Exact-token** (350: R@10 7/7, MRR 0.881): robust at every size, because BM25 finds the
  literal token. R@10 7/7 at both; MRR at 200 the same or slightly higher (a short chunk
  around the token scores well on BM25 length normalisation).
- **Multi-chunk** (350: full R@10 4/7, MRR 0.401): 500 helps, since the spans are more often
  in one chunk: full R@10 at least 5/7. 200 hurts, since spans spread over more chunks:
  full R@10 at most 4/7.
- **Factoid** (350: full R@10 15/17): within ±1 at both sizes.
- **Time:** ingestion about 6-7 min per size (350 took 350 s). Retrieval is faster than my
  first estimate: the reranker cache is keyed by text, so every chunk identical to a 350
  chunk is a cache hit. 500: under ~10 min; 200: about 10-20 min. Anything over 60 min stops
  the run.

### E4 result (measured), dev split, 41 answerable + 7 unanswerable

**Runs** (all E3 config: hybrid, rerank, candidates 40, expand none, limit 10; clean tree):

| size | tenant / tag | chunks | tokens | median / max per chunk | ingest (22/22 ready) | retrieval work time |
|---|---|---|---|---|---|---|
| 200 | `eval-c200`, `E4-c200` | 664 | 81,301 | 127 / 200 | 4 min 47 s | 10 min 51 s (wall = work, no alerts) |
| 350 | baseline, `E3-hybrid-rerank` | 473 | 74,423 | 132 / 350 | 350 s (M8 8.1) | 28 min 50 s |
| 500 | `eval-c500`, `E4-c500` | 424 | 72,643 | 121 / 500 | 6 min 59 s | **19.0 min** of measured work |

- The 500 run's wall time (12:48:20-13:41:10, ~53 min) includes **about 34 min of machine
  sleep**. The monitor saw a 2,088 s clock jump; per-question times, measured on a clock that
  doesn't count suspend, add up to 19.0 min. Use 19.0 min for any timing comparison. Scores
  are deterministic and unaffected. Accepted as is (your decision, no re-run).
- Retrieval times aren't comparable across sizes. The 350 run was fully uncached, while the
  200 and 500 runs reused cached rerank scores for every chunk text identical to a 350 chunk
  (303/664 at 200, 347/424 at 500). The CPU rerank cost per query is 350's (median 37.7 s).
- Ingestion used a local API with `RATE_LIMIT_UPLOAD_CAPACITY=50` (env only), so 22 uploads
  weren't throttled.

**Overall** (raw counts of questions with full recall; MRR and nDCG over 41):

| size | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| 200 | 18/41 | 24/41 | 30/41 | 34/41 | 0.596 | 0.681 |
| 350 | 20/41 | 27/41 | 31/41 | 34/41 | 0.635 | 0.706 |
| 500 | 20/41 | 26/41 | 30/41 | 34/41 | 0.638 | 0.704 |

**Per type** (R@1 / R@3 / R@5 / R@10, MRR):

| type | 200 | 350 | 500 |
|---|---|---|---|
| factoid (17) | 9/12/15/16, 0.669 | 10/12/14/15, 0.680 | 11/12/13/15, 0.709 |
| paraphrase (10) | 3/6/8/8, 0.445 | 4/8/8/8, 0.550 | 3/8/8/8, 0.500 |
| exact-token (7) | 6/6/6/7, 0.881 | 6/6/6/7, 0.881 | 6/6/7/7, 0.893 |
| multi-chunk (7) | 0/0/1/3, 0.349 | 0/1/3/4, 0.401 | 0/0/2/4, 0.406 |

**Questions that moved** (first-hit rank, R@3, R@10; vs 350):
- 350 -> 200, 12 moved:
  - **up (4):** q005 rank 5->4, q006 not found->8 (R@10 0->1), q015 6->4, q021 5->4. All
    factoid.
  - **down (8):** q018 1->2, q024 3->4 (R@3 lost), q025 1->3, q027 2->3, q033 3->5 (R@3 lost),
    q045 3->5 (R@3 0.5->0), q047 3->7 (R@3 1->0, R@10 1->0.5), q050 7->10 (R@10 0.67->0.33).
    That is all 4 paraphrase movers and all 3 multi-chunk movers.
- 350 -> 500, 12 moved:
  - **up (6):** q003 2->1, q005 5->4, q033 3->2, q034 6->4, q043 6->5, q046 3->2.
  - **down (6):** q015 6->7, q021 5->6, q025 1->3, q045 3->4 (R@3 0.5->0), q047 3->4 (R@3
    1->0), q050 R@10 0.67->0.33.
  - Most moves are one rank.

**Hypotheses vs result:**

| hypothesis (written before) | measured | verdict |
|---|---|---|
| Guide: mid size (350) best | 350 beats 200 on R@1 (+2), R@3 (+3), MRR (+0.039); 350 and 500 tie (R@3 27 vs 26, MRR 0.635 vs 0.638) | **right vs 200, inconclusive vs 500** |
| Chunks at 200: 620-720 | 664 | right |
| Chunks at 500: 430-460 | 424 | wrong (slightly fewer) |
| Under ~40% of chunks change at 200, under ~15% at 500 | 54% new texts at 200 (361/664), 18% at 500 (77/424) | wrong (both higher) |
| Overall R@10: 200 31-34, 500 34-36 | 34 and 34 | right (both at the edge) |
| MRR: 200 0.55-0.62, 500 0.62-0.67 | 0.596, 0.638 | right |
| Paraphrase: 200 hurts (R@10 6-8), 500 about the same (7-9) | R@10 8 / 8 / 8; at 200 R@3 8->6 and MRR 0.550->0.445; 500 R@3 8, MRR 0.500 | right (R@10 unchanged, harm shows at R@3/MRR) |
| Exact-token: R@10 7/7 at both, MRR at 200 same or higher | 7/7 at all sizes; MRR 0.881 / 0.881 / 0.893 | right |
| Multi-chunk: 500 full R@10 >= 5/7 | 4/7 | **wrong** (no gain) |
| Multi-chunk: 200 full R@10 <= 4/7 | 3/7 | right |
| Factoid within ±1 | 16 and 15 (350: 15) | right |
| Ingest about 6-7 min per size | 4 min 47 s, 6 min 59 s | half right (200 faster) |
| Retrieval: 500 under ~10 min, 200 10-20 min | 19.0 min, 10 min 51 s | 500 wrong, 200 right |

**Caveats:**
- **Easier targets.** A bigger chunk holds more text, so it is an easier target for span
  recall. Even so, 500 doesn't beat 350 at any k, and 200 (the harder target) ties 350 at
  R@10.
- **Noise.** With 41 answerable questions, one question is 2.4 points of recall. Differences
  of 1-2 questions (all R@10 and R@5 differences here, 350 vs 500 everywhere) are noise. The
  clearest signal is 200's loss at R@1/R@3/MRR, concentrated in paraphrase and multi-chunk
  (7 of its 8 down-moves), and even that is only 2-3 questions.
- **Size of the change.** Most chunks don't change with size: chunking is heading-bounded,
  and the median chunk is ~120-130 tokens at every size.
- **Scope.** One corpus, one split, one run per size; retrieval only, nothing about answer
  quality.

**Conclusion (measured, dev only):** keep 350. 200 is worse on early ranks (paraphrase and
multi-chunk), and 500 is indistinguishable from 350.

## Hold-out: the one final run (retrieval only), FINAL, not tuned on

Date: 2026-10-11, 16:26:02-16:33:09 UTC (7 min 7 s; estimated 8-10 min; per-question median
36.3 s, max 56.7 s, rerank uncached). Tag `E3-holdout`, `--final-holdout`, ADR-0012
configuration exactly: hybrid, rerank, candidates 40, expand none, limit 10; chunks 350/50 on
the original eval tenant. Clean tree (`e480f17`); no alerts (min available memory 5,072 MB,
no clock jump). The 12 hold-out ids, 10 answerable, match `v1.split.json`.

| | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| **hold-out (10 answerable)** | **5/10** | **8/10** | **9/10** | **9/10** | **0.670** | **0.732** |
| dev E3 (41 answerable) | 20/41 | 27/41 | 31/41 | 34/41 | 0.635 | 0.706 |

**The hold-out is not worse than dev.** It is about the same or slightly better at every k:
R@3 80% vs 66%, R@10 90% vs 83%. With 10 questions, one question is 10 points, so this is
within noise. It is no evidence that the configuration is better than dev says, only that it
didn't collapse on unseen questions.

Individual cases, not rates (n = 1-4 per type):
- factoid: q002, q011, q013 at rank 1; q009 at rank 5.
- paraphrase: q026 and q032 at rank 2.
- exact-token: q037 and q039 at rank 1.
- multi-chunk: q048 has both spans by rank 3 (first at rank 2); **q051 not found in the top 10
  at all**.
- unanswerable: q054 and q060 (retrieval only, no refusal scored).

Nothing was tuned, re-run or changed after these numbers. They are final for dataset v1.

## M10-1: weighted RRF, dense 1.5 and 2.0 vs BM25 1.0 (hypothesis written before any run)

Date: 2026-10-12. Dev split only (the v1 hold-out is spent). Retrieval only. `RRF_DENSE_WEIGHT`
(default 1.0, plain RRF; tests prove the default is unchanged). Weights 1.5 and 2.0 were
chosen before any run (your decision).

**Why** (failure analysis, bucket D): in 5 of the 8 ranking failures the gold chunk was a
dense-only hit that plain RRF ranked below chunks both lists found: q029, q031, q044 (dense
rank 1, fused 27), q049, q061.

**Runs:**
- **Main:** E3 (hybrid, rerank on, candidates 40, expand none, limit 10) with dense weight
  1.5 and 2.0. Tags `M10-rrf1.5`, `M10-rrf2.0`. This is what the final configuration
  (ADR-0012) would use.
- **Diagnostic:** E2 (hybrid, rerank off) with the same two weights. Tags
  `M10-e2-rrf1.5`, `M10-e2-rrf2.0`. Seconds each, no reranking. They show the fusion effect
  the reranker hides.

**Mechanism, before predictions:**
- With rerank on, the final order is the reranker's. Fusion only decides which candidates
  enter the reranker's 50-item window, out of up to 80 fused.
- In the E3 trace, 4 of the 5 dense-only golds were already inside the window and the
  reranker itself put them low: q029 at 24, q031 at 33, q044 span 2 at 23, q049 span 1 at
  11. For q061, fused rank 40 means it was in the window at both, but where the reranker put
  it is unclear from the trace.

**Predictions:**
- **E3 + weights:** about E3 at both weights, within ±1 question at every k (dev E3: R@1 20,
  R@3 27, R@5 31, R@10 34 of 41; MRR 0.635). None of the 5 cases gets into the top 6. If the
  window loses a gold chunk that BM25 alone found, exact-token could drop by 1; otherwise it
  stays at 7/7 at R@10.
- **E2 + weights** (dev E2: R@1 17, R@3 28, R@10 34, MRR 0.628): fused ranks of dense-only
  golds improve. At 2.0, q044 span 2 (dense rank 1) moves into the top 10. Paraphrase R@10 is
  +1 or +2 (measured E2: R@3 4/10, R@10 6/10, MRR 0.325). Exact-token MRR may drop from
  0.905, since BM25 matters most there.
- **Time:** E3 runs 5-20 min each (only new reranker pairs are uncached, about 0.9 s each);
  E2 runs under 1 min.
- **Decision rule, fixed now:** keep a weight in the final configuration only if E3 plus that
  weight beats E3 by at least 2 questions at R@3 or R@10 with no type losing more than 1.
  Otherwise keep 1.0: the default stays, and "didn't help" is recorded.

### M10-1 result (measured), dev only

Runs 2026-10-12 15:28-15:32 UTC, clean tree (`bddaca6`), boot time unchanged, min available
memory 5,975 MB. Times:
- E2 runs: 6-7 s each;
- E3 w1.5: 3 min 4 s (new reranker pairs only);
- E3 w2.0: 7 s (every pair already cached by the w1.5 run).

| dev, 41 answerable | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| **E3 w1.0 (baseline)** | 20 | 27 | 31 | 34 | 0.635 | 0.706 |
| E3 w1.5 | 20 | 27 | 32 | 35 | 0.639 | 0.714 |
| E3 w2.0 | 20 | 27 | 32 | 35 | 0.639 | 0.714 |
| E2 w1.0 (diagnostic) | 17 | 28 | 30 | 34 | 0.628 | 0.692 |
| E2 w1.5 | 17 | 26 | 31 | 34 | 0.623 | 0.688 |
| E2 w2.0 | 17 | 25 | 31 | 34 | 0.627 | 0.686 |

**Per type, R@3 / R@10 / MRR:**
- **E3:** identical at both weights except factoid (R@10 15 -> 16, MRR 0.680 -> 0.689).
  Paraphrase stays 8/8/0.550, exact-token 6/7/0.881, multi-chunk 1/4/0.401.
- **E2 at 2.0:** paraphrase MRR 0.325 -> 0.365, but R@3 4 -> 3; exact-token MRR 0.905 ->
  0.833; factoid R@3 15 -> 13.

**Questions that moved:**
- **E3, both weights:** 2. q006 went from not found to rank 9 (R@10 0 -> 1), q015 from 6 to
  5.
- **E2 at 2.0:** 11, mostly by one rank, with ups and downs in every type. The 5 target cases
  (q029, q031, q044, q049, q061) didn't move into the top 10 at either weight, in E2 or E3.

**Hypotheses vs result:**
- E3 within ±1 question of E3 at every k: **right** (R@5 and R@10 each +1).
- None of the 5 dense-only cases gets into the top 6: **right** (none moved).
- Exact-token stays 7/7 at R@10 in E3: **right**.
- E2 at 2.0 puts q044 span 2 in the top 10: **wrong** (it didn't move).
- E2 paraphrase R@10 +1 or +2: **wrong** (6 -> 6; only MRR rose, 0.325 -> 0.365).
- E2 exact-token MRR may drop: **right** at 2.0 (0.905 -> 0.833).
- Time, E3 5-20 min each: **wrong**, faster (3 min 4 s and 7 s, thanks to the cache).

**Decision, by the rule fixed beforehand: keep `RRF_DENSE_WEIGHT=1.0`.** E3 gained 1 question
at R@10, below the required 2, so the default is unchanged; the setting stays available.
Weighted fusion can't fix the ranking failures while the reranker decides the final order
and itself ranks those golds low; it mostly reshuffles E2. The next lever for bucket D is the
reranker (or the candidates it sees), not fusion.

**Dev-only caveat:** dev has been used for every choice so far. One question is 2.4 points,
so +1 at R@5 and R@10 is noise.

## M10-2: the quote-then-cite answer prompt (hypothesis written before the run)

Date: 2026-10-12. Dev split only (48 questions; the v1 hold-out is spent). Generation with
llama3.2:3b on Ollama, no Anthropic. Tag `M10-quote`.

**Configuration:** E3 retrieval exactly as ADR-0012 (hybrid, rerank, candidates 40, expand
none, limit 6; `RRF_DENSE_WEIGHT` stays 1.0 after M10-1), with
`ANSWER_STYLE=quote_then_cite` (`app/prompts/rag_system_quote.md`). The default stays
`cite`, and tests prove it renders the M5 prompt unchanged. The new prompt keeps ADR-0007's
rules verbatim (also tested) and changes only the refusal wording ("no document contains a
sentence that answers") and the answer form:

    Quote: "<the answering sentence, copied exactly>" [N]
    Answer: <one or two sentences, [N] after each claim>

**Why** (failure analysis): context use is the largest bucket (14 of 26), plus hallucination
and refusal (4). In 8 of the 14 context-use cases the answer cites a non-gold source while the
gold source is in the prompt.

**Baseline:** E3-gen, re-scored with the current checks and cleanup
(`eval/runs/E3-gen/rescore.json`):
- **Answered:** 40, of which 15 cite a gold source and 6 are uncited; 4 have malformed
  citations.
- **Refusals (7 unanswerable):** 4 correct, 2 near, 1 missed (the bare "[6]"); 1 false
  refusal on the 41 answerable.
- **Citations:** 40 valid / 0 invalid.
- **Facts:** all found in 7 of 23 checkable answers, mean share 0.49.
- **Speed:** generation median 120 s, max 230 s.

**Measurement rules, fixed now:**
- The same deterministic checks as the baseline.
- **Facts on the Answer: part only:** the quote is copied from a document, so it can lift
  the fact count by copying alone. Facts are reported both on the whole answer and on the
  text after "Answer:" (the whole answer if there is no such line).
- **Format compliance:** the share of answered questions with both a "Quote:" line and an
  "Answer:" line.

**Predictions:**
- **Cites a gold source:** 15/40 -> 20-26/40.
- **Uncited answers:** 6 -> 0-2. **Bare-citation answers:** (q040 "[5]", q053 "[6]") 2 -> 0.
- **Refusals:** correct 4/7 -> 4-6/7; near 2 -> 0-1; missed 1 -> 0-1. **False refusals:**
  1 -> 1-3, since the stricter "no sentence answers" rule may refuse more.
- **Facts all found (23 checkable):** 7 -> 7-11 on the whole answer, 6-10 on the Answer: part.
- **Format compliance:** at least 80% of answered questions. A 3B model may not follow the
  format; if it falls below 50%, that is the main finding.
- **Latency:** median 120 s -> 130-170 s; the first token (about 107 s) dominates and the
  quote adds output.

**Decision rule, fixed now:** make `quote_then_cite` the default only if all three hold:
- cites-gold reaches at least 19/40 (+4);
- correct refusals stay at least 4/7, and false refusals at most 2;
- facts all-found doesn't drop on the Answer: part.

Otherwise keep `cite`, and record why.

**How it runs** (your conditions):
- **Batches:** three batches of 16 dev ids under one tag, so the run is resumable with one
  line written per question. `ollama stop` and at least 6 GB available before each batch,
  then a final call without `--ids` for the summary.
- **Monitor:** progress, memory and clock. Stop and tell you on less than 1.5 GB available, a
  single answer over 5 minutes, or signs of sleep.
- **Time:** estimated 105-135 min. Retrieval is cached from E3-gen, so this is generation
  only.

### M10-2 result (measured), dev only

**The run:** 2026-10-12 15:49-17:37 UTC, 107 min. Three batches of 16, with `ollama stop`
between them and 8.0-8.4 GB available at each start. 48/48 written, 0 errors, no answer
over 5 minutes, min available memory 1,981 MB. Clean tree (`161c7f1`).

**The clock:** the boot time computed from uptime moved from 11:34:30 to 11:39:10 during the
run. Wall clock and uptime drifted about 4.7 min apart in total, with no single jump over
30 s in any 15 s check, so it looks like gradual corrections, not a sleep. Answer timings
use a monotonic clock and are unaffected.

| check | E3-gen, re-scored (`cite`) | M10-quote (`quote_then_cite`) |
|---|---|---|
| answered (of 41 answerable) | 40 | 41 |
| **answered, citing a gold source** | 15/40 | **21/41** |
| answered without any citation | 6 | **0** |
| answers with malformed citations | 4 | **0** |
| bare-citation answers (only "[N]") | 2 (q040, q053) | **0** |
| numeric citations valid / invalid | 40 / 0 | 50 / 1 (q031 cited [7] of 6) |
| format compliance (Quote: and Answer: lines) | n/a | 41/41 |
| **exact correct refusals (of 7)** | **4** | **0** |
| near-refusals / missed | 2 / 1 | 4 / 3 |
| false refusals (of 41) | 1 (q061) | 0 (but see q061 below) |
| facts all found, whole answer | 7/23 | 9/24 |
| **facts all found, Answer: part only** | 7/23 | **5/24** (mean share 0.453) |
| generation median / max | 120 s / 230 s | 126 s / 203 s (first token 104 s) |

**What happened:**
- **The format is followed perfectly,** and it removed every uncited, malformed and bare
  answer. q040 now answers "Q4_K_M [1]" where it used to answer "[5]".
- **Answers citing a gold source rose by 6.**
- **But the model now writes a Quote: line for every question, unanswerable ones
  included.** It then either hedges (q052, q053, q056 and q058 are near-refusals) or uses
  an irrelevant quote as if it answered: q055 gives rate-limit numbers as "payment methods".
- **Refusals no longer match the exact sentence,** even when the model does refuse. q061's
  output is `Quote: "…" [5]` followed by `Answer: I can't answer that from the provided
  documents.` The exact-match refusal check fails on it, and so would the app's own
  `done.refused` flag. Refusal is broken in the app too, not only in the eval.
- **q057 is a label nuance:** "No SLA is defined for the Enterprise plan" is arguably a
  correct answer from the corpus; v1 labels the question unanswerable (v1 is locked).
- **Facts on the answer itself fell** (5 vs 7 all found). The whole-answer gain to 9 comes
  from copied quote text, as the measurement rule anticipated.

**Hypotheses vs result:**
- Cites a gold source 20-26/40: **right** (21/41).
- Uncited answers 0-2: **right** (0). Bare-citation answers 0: **right**.
- Correct refusals 4-6/7: **wrong**, 0/7.
- Near-refusals 0-1: **wrong**, 4. Missed 0-1: **wrong**, 3.
- False refusals 1-3: **right** by the check (0), but q061 is a refusal hidden behind a quote.
- Facts all found 7-11 on the whole answer: **right** (9). 6-10 on the Answer: part:
  **wrong** (5).
- Format compliance at least 80%: **right** (100%).
- Median latency 130-170 s: **wrong**, faster (126 s).

**Decision, by the rule fixed beforehand: keep `ANSWER_STYLE=cite`.** Cites-gold passed
(21 >= 19), but correct refusals fell below 4/7 (0/7) and Answer:-part facts dropped (7 ->
5). The setting stays available.

**What it teaches** (not run; a possible follow-up, needs your approval):
- The grounding gain is real, and the refusal loss comes from the format. A next variant
  would put the refusal decision first ("If no document answers, reply only with the
  refusal sentence; otherwise Quote:/Answer:"), and the app could strip `Quote:` before the
  exact refusal check.
- It needs another ~107 min dev run. With a 3B model, a prompt rule may again be ignored.

**Dev-only caveat:** dev has been used for every choice so far, and n = 7 for refusals
(one question is 14 points).

## M10-3: refusal-first quote-then-cite (hypothesis written before the run)

Date: 2026-10-12. Dev split only (48 questions), llama3.2:3b on Ollama, no Anthropic. Tag
`M10-quote-rf`. The retrieval is the same as M10-2 (ADR-0012, `RRF_DENSE_WEIGHT` 1.0).

**The change:** `ANSWER_STYLE=quote_refusal_first`
(`app/prompts/rag_system_quote_refusal_first.md`). Rule 1 now asks for the refusal decision
first: if no document answers, reply with exactly the refusal sentence, which sits alone on
its own line, and "a refusal has no Quote line, no Answer line and no other text". Rule 2
(Quote:/Answer:) applies only otherwise. Rules 3-6, the ADR-0007 rules, are word for word
those of `rag_system.md` (tested). The default stays `cite` (tested). The app is unchanged:
no stripping of `Quote:` before the refusal check, so the run measures the prompt alone.

**Why:** M10-2 showed the gain in grounding (cites-gold 15 -> 21, uncited and malformed 0)
and the loss in refusals: 0/7 exact, because the model wrote a Quote: line for every
question, refusals included (q061 "Quote: ... Answer: I can't answer ...").

**Baselines:**
- E3-gen re-scored (`cite`): refusals 4/7 correct, 2 near, 1 missed; 1 false refusal of 41;
  cites-gold 15/40; uncited 6; malformed 4.
- M10-quote (`quote_then_cite`): refusals 0/7 correct, 4 near, 3 missed; 0 false refusals;
  cites-gold 21/41; uncited 0; malformed 0.

**Decision rule (yours, fixed now):** `quote_refusal_first` wins only if all of these hold;
otherwise `cite` stays the default:
- exact correct refusals at least 4 of 7;
- false refusals do not increase: at most 1, E3-gen's count;
- answers citing a gold source at least 20/41;
- uncited and malformed answers stay near 0, fixed now as at most 2 each.

**Predictions:**
- **Exact correct refusals:** 0 -> 2-4/7. I expect this rule to be the one that decides,
  and more likely to fail than pass. In M10-2, q055, q057 and q059 used an irrelevant quote
  as an answer. A 3B model choosing the format before it judges relevance won't be fixed by
  order alone. q057 ("no SLA defined") is likely still answered.
- **Near-refusals:** 4 -> 1-3. Refusal-like answers should become exact more often.
- **False refusals:** 0-2. Refusal-first may make the model quicker to refuse.
- **Cites a gold source:** 18-22/41, about the same as M10-2. Grounding comes from the
  quote, which still applies to answers.
- **Uncited:** 0-1. **Malformed:** 0-1.
- **Format compliance** (answers with Quote: and Answer:): at least 90%.
- **Facts all found** on the Answer: part (24 checkable): 4-7.
- **Generation median:** 120-135 s; refusals are short.

**How it runs** (your conditions, as in M10-2): three batches of 16, with `ollama stop` and at
least 6 GB available before each batch, then a summary call. A monitor watches progress,
memory and the clock. It stops and tells you on less than 1.5 GB available, a single answer
over 5 minutes, or signs of sleep. One line is written per question.

**Dev-only caveat:** n = 7 for refusals (one question is 14 points), and dev has been used for
every choice so far.
