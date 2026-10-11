# M8 failure analysis (guide 8.7, buckets A-G)

Date: 2026-10-11. Dev split only (dataset v1); the hold-out was not looked at. Configuration:
ADR-0012 (E3: hybrid, rerank, candidates 40, expand none, chunks 350/50). Retrieval results
come from `eval/runs/E3-hybrid-rerank` and answers from `eval/runs/E3-gen` (limit 6,
llama3.2:3b). No code was changed.

## Method and evidence

- **Debug trace.** A scratch script (outside the repo) re-ran `retrieve(trace=True)` with the
  E3 config for the 41 answerable dev questions. All rerank scores came from the cache, so the
  run took 20 s. It recorded the rank of every chunk holding a gold span in the dense, sparse,
  fused and reranked lists and in the final top 10. Its final ranks match E3 for all 41
  questions (0 mismatches).
- **In the corpus, chunked intact (A, B).** `tests/integration/test_eval_spans.py` checks all
  63 gold spans against the parser's output. Every gold span of all 41 answerable questions
  is contained whole in at least one 350-token chunk (measured on the chunk table). So **A = 0
  and B = 0** across the dev set.
- **In the prompt.** The span is in one of the 6 sources stored with the E3-gen answer.
- **Claims.** I read each wrong or partial answer against its sources. Where you hand-graded
  the answer (15 of them), your grade is the ground truth. Otherwise the call is my reading,
  marked "(mine)". The LLM judge isn't used (ADR-0011).
- **Labels (G).** I re-read the gold span and reference of every failing question.

A question is a failure if:
- its gold isn't fully in the top 10; or
- part of its gold is ranked 7-10 (so outside the 6 sources chat sends); or
- its answer is wrong or partial; or
- an unanswerable question isn't refused exactly.

Each question gets one bucket: the earliest stage that failed.

## Summary

| bucket | count | questions |
|---|---|---|
| A. Parse loss | 0 | (all spans parsed and present) |
| B. Chunking | 0 | (every span intact in one chunk) |
| C. Retrieval miss | 0 | (every missed gold chunk was a dense candidate in the top 40) |
| **D. Ranking** | **8** | q006, q029, q031, q043, q044, q049, q050, q061 |
| **E. Context use** | **14** | q001, q012, q014, q021, q024, q027, q028, q033, q034, q036, q040, q042, q046, q047 |
| F. Hallucination / refusal | 4 | q045, q053, q055, q058 |
| G. Label error | 0 | (none found) |

That is 26 failing questions of 48: 23 of 41 answerable and 3 of 7 unanswerable. The other
18 answerable questions had all their gold in the prompt and were answered correctly, by
your grades where you graded them and by my reading otherwise.

## D. Ranking: in the candidates but ranked too low (8)

Ranks are 1-based: dense (top 40) / sparse (top 40, "-" = not returned) / fused / reranked;
"final" is the position in the top 10.

| id | type | gold chunk ranks d / s / fused / rerank | final | in prompt | answer | fix idea |
|---|---|---|---|---|---|---|
| q006 | factoid | 2 / 15 / 2 / 12 | - | no | partial (mine) | the reranker demoted a chunk fusion had at 2; keep the fused top 1-2 above the rerank cut |
| q029 | paraphrase | 17 / - / 35 / 24 | - | no | partial (mine) | dense-only hit sunk by RRF; weighted RRF (dense > sparse) |
| q031 | paraphrase | 11 / - / 23 / 33 | - | no | wrong (mine): uuid5 point ids, misapplied from CLAUDE.md | dense-only hit sunk by RRF; weighted RRF |
| q043 | multi-chunk | span 1: 1 / 4 / 1 / 6; span 2: 3 / 11 / 4 / 8 | 6, 8 | 1 of 2 | not graded | the reranker spread a two-part answer past 6; multi-span aware ordering, or limit 8 |
| q044 | multi-chunk | span 2 (docs page): **1** / - / 27 / 23 | - | 1 of 2 | yours 2 / n | dense rank 1 sunk to 27 by RRF (BM25 didn't return it); weighted RRF |
| q049 | multi-chunk | span 1: 16 / - / 27 / 11 | - | 1 of 2 | partial (mine) | dense-only hit sunk by RRF |
| q050 | multi-chunk | 3 spans: rerank 9, 16, 7 | 7, 9 | 0 of 3 | right but uncited (mine); facts 1.0 | three spans in three docs; none in the top 6 |
| q061 | factoid | 21 / - / 40 / 47 | - | no | false refusal | heavy paraphrase ("sensors / gateway / frequency" for widgets / hub / radio channel); dense-only and deep |

- In **5 of 8** (q029, q031, q044, q049, q061), BM25 didn't return the gold chunk, so RRF
  ranked it below chunks both retrievers found. q044's gold was **dense rank 1** and fused 27.
  This is the M4 hypothesis (plain RRF hurts paraphrases when the sparse list misses), now
  with evidence.
- In q006 the **reranker** demoted the gold (fused 2 -> reranked 12).
- In the two-to-three-span questions (q043, q050), the spans are ranked 6-16, around the
  6-source cut.

## E. Context use: the gold was in the prompt but the answer ignored or misread it (14)

| id | type | gold in source | cited | what went wrong | grade | fix idea |
|---|---|---|---|---|---|---|
| q012 | factoid | [1] | [2] | right quote, wrong source number | yours 2 / n | quote-then-cite prompt |
| q014 | factoid | [1] | [3] | used [3] (a different list), said it "does not explicitly state"; citation fused (`[3]RIGHT-09`) | wrong (mine) | quote-then-cite prompt |
| q024 | paraphrase | [3] | [4] | answered from an unrelated deletion note in [4] | yours 0 / n | quote-then-cite prompt |
| q027 | paraphrase | [2] | [2] | quoted a different sentence of [2], then inferred the answer ("This implies ...") | yours 2 / n | quote-then-cite prompt |
| q028 | paraphrase | [3] | [2] | gave [2]'s consequences instead of [3]'s reason | wrong (mine) | quote-then-cite prompt |
| q033 | paraphrase | [3] | [2] | answered from [2] (ownership rules), not the DB-level reason in [3] | wrong (mine) | quote-then-cite prompt |
| q040 | exact-token | [1] | [5] | answer is only "[5]" | wrong (mine) | quote-then-cite; reject a bare citation |
| q042 | exact-token | [1] | [2] | "restricts" where [1] says "pre-approves" | wrong (mine) | quote-then-cite prompt |
| q046 | multi-chunk | [3], [5] | [2] | wrong mechanism for forged citations | yours 1 / n | quote-then-cite prompt |
| q001 | factoid | [1]-[6] | none | right, but uncited and without the two-year tier | partial (mine) | cite-every-claim reminder |
| q021 | factoid | [5] | [5] | pasted the whole table instead of answering | yours 1 / y | answer-in-one-sentence rule |
| q034 | exact-token | [6] | none | described dashboard calibration, not the CLI reference reading; `<answer>` wrapper | yours 1 / y | quote-then-cite prompt |
| q036 | exact-token | [1] | [1] | default right, range 0-60 missing | yours 1 / y | (minor) |
| q047 | multi-chunk | [3] | [3] | login per-email limit missing | partial (mine) | (minor) |

- In **8 of 14** (q012, q014, q024, q028, q033, q040, q042, q046), the answer cites a
  non-gold source although the gold source is in the prompt. In **4** of them (q012, q014,
  q040, q042) the gold is source [1], the top-ranked one.
- Only 15 of 40 answered questions cite a gold source at all (E3-gen deterministic check).
- The fix direction for E is the prompt, the model or the chunk order. The order isn't the
  problem here (the gold is often [1]).

## F. Hallucination and refusal failures (4)

| id | type | evidence | fix idea |
|---|---|---|---|
| q045 | multi-chunk | gold in [3] and [4], cited [2]; the claim that the query rewrite made the difference is not in any source | quote-then-cite prompt (grounding) |
| q053 | unanswerable | answer is only "[6]" | reject a bare citation and refuse instead |
| q055 | unanswerable | pasted two unrelated sources, then "There is no mention of payment methods" (near-refusal) | stricter refusal rule in the prompt |
| q058 | unanswerable | "not explicitly stated ... however" plus a quote (near-refusal) | stricter refusal rule in the prompt |

## G. Label errors (0)

None of the failing questions' gold spans or references is wrong. One note, not an error:
q061 is labelled factoid but reads as a heavy paraphrase. That affects only per-type
counts, and changing it would make a dataset v2.

## Recommendation: the single top fix (not applied)

**E is the largest bucket (14 of 26), and its dominant pattern is citing or using the wrong
source while the right one is in the prompt.** The recommended fix is a grounding change to
`app/prompts/rag_system.md`:
- before answering, the model quotes the sentence that answers the question, from one
  document;
- it cites that document's number;
- it answers in one or two sentences;
- if no document has such a sentence, it gives the exact refusal.

It targets 8-10 of the E cases plus q045, q053, q055 and q058, and it needs no retrieval
change. It can be measured with the deterministic checks that already exist:
- `answered_citing_gold` (15/40 now);
- refusal outcomes (4 correct / 2 near / 1 missed of 7; 1 false refusal);
- malformed and bare citations;
- facts all-found (7/23).

It also needs one dev generation run, about 100 min, which needs your approval.

- **Risk.** A 3B model may follow a longer instruction worse, and quoting adds output
  tokens and so time. "Didn't help" is a possible, reportable outcome.
- **Why not "fewer sources"** (limit 6 -> 3) to cut distractors: in the top 3, 27/41
  questions have full gold recall, against 33/41 in the top 6. Six questions (q005, q015,
  q021, q034, q045, q046) would lose their gold from the prompt.
- **Runner-up, for bucket D:** weighted RRF (or fusing with the dense rank weighted above
  BM25). 5 of the 8 D cases are dense-only hits sunk by plain RRF. It would need a retrieval
  experiment on dev and a re-check of exact-token, where BM25 matters.
