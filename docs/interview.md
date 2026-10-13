# Interview notes

Talking points and answers for the guide's M11 question banks, drawn from this project only.
Every number has its raw count and the file it comes from; if it isn't in a file, it isn't
here. Numbers were measured on one laptop CPU with free local models (BGE, BM25,
bge-reranker-base, Ollama llama3.2:3b), one run each.

**The caveat to say first:** every retrieval and prompt choice was made on the same 48 dev
questions. The 12-question hold-out was run once, at the end, for retrieval only. Dev numbers
are not a fresh estimate (see "What didn't work" and the README).

## Resume bullets (measured numbers only)

Each bullet follows the guide's M11.1 template. Tags after a number:
- **[dev]:** measured on the 48 dev questions that every choice was also made on;
- **[n = ...]:** a small sample;
- **[unverified]:** not checked where the claim would apply.

Don't drop the tags when you're asked about a number.

- Built **Nexus RAG**, a multi-tenant document Q&A API (FastAPI, Postgres, Qdrant, Celery,
  Redis) with hybrid dense + BM25 retrieval, RRF fusion and cross-encoder reranking.
  - Raised Recall@5 from 0.630 to 0.780 (questions with every gold span in the top 5: 24/41
    to 31/41) and MRR from 0.532 to 0.635 over dense-only retrieval, on the 41 answerable dev
    questions of a 60-question labelled set **[dev]**.
  - On the 12-question hold-out, run once: R@5 9/10, MRR 0.670 **[n = 10]**.
- Enforced tenant isolation with:
  - token-derived tenant identity;
  - a single filtered vector-store gateway, enforced by import-linter contracts;
  - tenant-scoped Postgres queries and composite foreign keys.
  - Verified by 26 cross-tenant and IDOR integration tests plus 21 API-key tests (collected
    with parametrization; 14 and 11 test functions). All run in the CI workflow **[CI
    unverified on GitHub]**.
- Designed a grounded, streaming (SSE) answer pipeline with server-validated citations, an
  explicit refusal path and query rewriting for multi-turn chat.
  - Citations: 40 valid, 0 invalid numeric citations **[dev]**; but 6/40 answers are
    uncited, only 15/40 cite a gold source, and 4 contain malformed brackets the numeric check
    can't see.
  - Refusals: 4/7 exact correct refusals and 1/41 false refusals **[dev, n = 7 for
    refusals]**.
  - Hand-graded: 10/15 answers faithful **[n = 15, one grader]**.
- Built an evaluation harness (retrieval metrics, deterministic answer checks) and ran
  controlled experiments on chunk size (3 sizes), fusion, reranking and two grounding
  prompts, each with a hypothesis and decision rule committed before the run.
  - Rejected an LLM judge that failed calibration against hand grades: 7/15 agreement vs
    10/15 for a constant **[n = 15]**.
  - Documented 17 decisions as ADRs.
- Exposed retrieval to coding agents as a read-only, tenant-bound MCP server.
  - Instrumented every answer with a query trace (per-stage latency, candidate ids and scores,
    model).
  - Container image and compose profile verified from a fresh clone; CI with lint, unit and
    integration jobs **[CI unverified on GitHub]**.
- Developed with Claude Code using:
  - a committed CLAUDE.md, permission deny rules and three hooks (protected files, format,
    test gate);
  - two subagents, a skill and two commands.
  - The security-review subagent's 6 reviews found 3 high- and 11 medium-severity issues,
    all fixed with tests first.

**Don't claim:**
- a faithfulness score from an LLM judge;
- cost accounting (`est_cost` is null on the free stack);
- embedding throughput (only end-to-end ingestion was timed: 473 chunks in 350 s);
- production traffic;
- CI passing on GitHub.

## The two-minute pitch

1. **Problem:** LLMs don't know a company's private documents and can't cite them; a SaaS
   needs grounded answers per customer, with no customer ever seeing another's data.
2. **What I built:** Nexus RAG, a multi-tenant document Q&A API.
   - Ingestion is async: Celery parses, chunks (350 tokens) and embeds dense and BM25 vectors.
   - Retrieval is hybrid: dense plus BM25, reciprocal rank fusion, then a cross-encoder
     reranker.
   - Answers stream over SSE, with citations checked server-side and an explicit refusal.
   - Also: multi-turn conversations with query rewriting, traces, and a read-only MCP server.
3. **The interesting engineering:**
   - **Isolation is an enforced, tested property, not a convention.** The tenant comes only
     from the token, and one gateway filters every Qdrant call. It's proved by 26
     cross-tenant tests plus 21 API-key tests (collected, with parametrization).
   - **Choices came from an evaluation set.** Hybrid + rerank lifted Recall@5 from 24/41
     (dense only) to 31/41, and MRR from 0.532 to 0.635 on dev.
4. **What's next:**
   - grounding (the model ignores the right source in 14 of 26 failures);
   - a fresh labelled set (dataset v2) for a clean final check;
   - document-level ACLs and a scheduled trace purge before any public deployment.

## Whiteboard (under a minute)

Draw the README's Mermaid diagram:
- **Two paths:**
  - ingestion: upload -> Redis -> worker -> Postgres + Qdrant;
  - query: API -> retrieval -> generation.
- **Where data lives:**
  - Postgres: tenants, users, documents, chunk text, conversations, API-key hashes, query
    traces;
  - Qdrant: one collection, 768-dim cosine dense vectors plus BM25 sparse vectors, with
    `tenant_id` in the payload (`is_tenant` index);
  - Redis: the Celery broker and rate-limit buckets.
- **Where isolation is enforced:**
  1. **Token:** `get_tenant_id` reads the tenant from the verified JWT or API key; bodies
     reject a `tenant_id` field (`extra="forbid"`).
  2. **Gateway:** `app/repositories/vector_store.py` adds the tenant filter to every search
     and delete. An import-linter contract stops any other module from importing the Qdrant
     client.
  3. **Postgres:** every repository query is scoped by tenant, and composite foreign keys
     tie each owner to its tenant.
  4. **Tests:**
     - `tests/integration/test_isolation.py` (7 functions) and `test_conversations_idor.py`
       (7 functions): 26 collected tests with parametrization;
     - `test_api_keys.py` (11 functions, 21 collected tests).

## Numbers to know (raw counts, sources)

| claim | number | source |
|---|---|---|
| Eval set | 60 questions, 22-file corpus; dev 48 (41 answerable, 7 unanswerable), hold-out 12 (10 + 2) | `eval/datasets/`, README |
| Corpus at 350 tokens | 473 chunks, 74,423 tokens, median 132 per chunk | `docs/decisions/eval-log.md` (E4 table) |
| Dense only (E0) | R@5 24/41, R@10 31/41, MRR 0.532 | `eval/runs/E0-dense/`, README |
| Hybrid RRF (E2) | R@5 30/41, R@10 34/41, MRR 0.628 | `eval/runs/E2-hybrid/` |
| Hybrid + rerank (E3, chosen) | R@1 20/41, R@5 31/41, R@10 34/41, MRR 0.635, nDCG@10 0.706 | `eval/runs/E3-hybrid-rerank/`, ADR-0012 |
| Hold-out, E3, run once | R@5 9/10, R@10 9/10, MRR 0.670 (one question = 10 points) | `eval/runs/E3-holdout/` |
| Correct refusals (exact) | 4/7; 2 near-refusals, 1 missed | `eval/runs/E3-gen/rescore.json` |
| False refusals | 1/41 | same |
| Citations | 40 valid, 0 invalid; 6/40 answers uncited; 15/40 cite a gold source; 4 answers with malformed brackets | same; `docs/decisions/eval-log.md` |
| Facts | all reference facts found in 7 of 23 checkable answers, mean share 0.49 | same |
| LLM judge (3B) vs 15 hand grades | correctness 7/15 vs 10/15 for always answering "2"; faithfulness 8/15 vs 10/15 | ADR-0011 |
| Hand grades | n = 15: correctness 0/1/2 = 1/4/10; faithful 10/15 | README, `eval/calibration/`, ADR-0011 |
| Rerank cost | about 38 s per query (median, uncached) vs 0.06 s without | README, eval-log |
| Answer latency | generation median 120 s (max 230 s), first token median 107 s, llama3.2:3b on CPU | `eval/runs/E3-gen/` |
| Ingestion, end to end | 473 chunks (22 files) in 350 s; 664 chunks in 4 min 47 s (one worker, CPU) | eval-log (E4) |
| Tests | 732 unit, 413 integration (2026-10-13) | `make test`, `make test-int` logs |
| Security reviews (subagent) | M5: 1 high, 3 medium; M6: 3 medium; M7: 2 high, 5 medium, all fixed with tests first; M4, M8, M9: none above low | `docs/PROGRESS.md` |
| Fresh clone | `make fetch-models` 484 s (1.3 GB); `make app-up` 137 s | README |

## Scale-up numbers

- **Vector storage:** a 768-dim float32 vector is 768 x 4 = 3,072 bytes.
  - **Here:** 473 chunks x 3,072 B = about 1.45 MB of raw dense vectors (arithmetic, not
    measured).
  - **At 1M chunks:** about 3.1 GB raw, plus HNSW overhead (often 1.5-2x), sparse vectors
    and payload. int8 quantization cuts the dense part about 4x; I'd verify the recall cost
    on the eval set before turning it on.
- **Throughput:** I measured ingestion end to end, not embedding alone: about 1.35 chunks/s
  (473 in 350 s) with one CPU worker. That figure includes parsing, chunking, sparse vectors
  and the upload rate limit.
- **What I'd do under each pressure:**

  | pressure | what I'd do, and what exists today |
  |---|---|
  | ingestion | more Celery workers; batch embedding; a GPU or a dedicated embedding service. Tasks are already idempotent (deterministic chunk ids, `delete_stale`) |
  | query latency | the reranker dominates (38 s on CPU): a GPU, a smaller reranker, or a smaller window; cache query embeddings |
  | many tenants | keep one collection with the `is_tenant` index; move very large tenants to their own collection |
  | cost | refusal short-circuit (no chunks, no LLM call: 0.38 s in the demo); prompt caching; a cheaper model for rewriting |
  | reliability | retries with backoff (3, tested), a dead-letter queue, health checks, graceful shutdown (compose `stop_grace_period`) |
  | security | Postgres row-level security as a second lock; document ACLs; a scheduled trace purge; a per-tenant API-key cap |

## RAG question bank (M11.6), answered from this project

1. **Pipeline end to end?**
   - Upload -> sniff type, cap size -> Celery: parse (pymupdf4llm for PDFs) -> chunk by
     tokens with headings -> embed dense + sparse -> upsert to Qdrant, with text in Postgres.
   - Query -> dense top 40 + BM25 top 40 -> RRF -> rerank top 50 -> best 6 in `<document>`
     tags -> stream -> validate citations.
   - Each stage exists for a measured reason: dense for paraphrases, BM25 for exact terms,
     rerank for ordering.
2. **Hardest part?**
   - Ingestion quality first: a scanned PDF has no text, and we fail it cleanly.
   - Here, though, the measured hardest part was generation. Retrieval found the gold chunk
     in the top 10 for 34/41 dev questions, yet the 3B model mis-used the context in 14 of
     26 failures.
3. **Chunk size?**
   - Swept 200 / 350 / 500 tokens on dev (E4): R@5 30/41 / 31/41 / 30/41, MRR 0.596 /
     0.635 / 0.638.
   - The differences are within noise (one question is 2.4 points), so 350 stays.
   - Overlap (E5) was not swept: deferred.
4. **Dense vs sparse vs hybrid?**
   - Dense R@10 31/41, BM25 25/41, hybrid 34/41.
   - BM25 wins on exact tokens (error codes, flags), dense on paraphrases.
   - Fused with RRF.
5. **Why RRF over adding scores?**
   - Cosine and BM25 scores are on different, query-dependent scales. RRF uses only ranks
     (1/(k + rank), k = 60), so no calibration is needed.
   - Weighting the dense list 1.5x or 2x moved 2 questions (M10-1), so plain RRF stays.
6. **Bi- vs cross-encoder?**
   - The bi-encoder embeds the query and document separately: fast and indexable.
   - The cross-encoder reads both together: precise, but about 38 s per query for 50 pairs
     on this CPU.
   - Hence "retrieve broad (40 + 40), rerank narrow (50), send 6".
7. **HNSW, m and ef?**
   - A layered proximity graph. `m` is the number of links per node (memory vs recall);
     `ef` is the search breadth (latency vs recall).
   - I used Qdrant's defaults and didn't tune them; at 473 chunks exact and approximate
     search barely differ. Say so if asked.
8. **Cosine vs dot vs Euclidean?**
   - The collection uses cosine. For normalised vectors (BGE outputs unit vectors) all
     three give the same ranking.
   - Normalising makes dot product equal cosine, which is cheaper.
9. **Model name in the collection name?**
   - The collection is `chunks__bge-base-en-v1_5`. Vectors from different models aren't
     comparable.
   - To migrate: build a new collection, re-embed, switch the setting, delete the old one.
     Deterministic chunk ids keep it idempotent.
10. **Preventing cross-tenant leakage?**
    - The attack paths: a tenant id in a body or query, IDOR on ids, a missing filter in one
      query, and the cache, cursors and traces.
    - The defences: the token-only tenant, `extra="forbid"`, one filtered gateway (with
      import-linter), Postgres scoping and composite FKs, HMAC cursors bound to scope, and
      404 (not 403) for others' objects.
    - Proved by 26 cross-tenant tests. The search one is parametrized over 5 switch
      combinations and was checked to fail with the Qdrant tenant condition removed
      (`3c502f8`).
11. **Evaluating retrieval vs generation, and LLM-judge pitfalls?**
    - Retrieval: Recall@k, MRR and nDCG against labelled spans.
    - Generation: deterministic checks (exact refusal, citation validity, gold-source
      citation, reference facts).
    - The judge: our 3B judge failed calibration against 15 hand grades (7/15 vs a 10/15
      constant baseline). It scored all 3 unanswerable questions 0, including 2 correct
      refusals, so it isn't used (ADR-0011).
12. **It hallucinates: how to debug?**
    - Take the trace (`GET /v1/traces/{request_id}`): was the gold chunk retrieved, ranked,
      sent, used?
    - Bucket the failures (A-G); here, 26 failures (`failure-analysis.md`).
    - Bucket E, context use, was the largest at 14. In 8 of those the answer cited a
      different source while the gold one was in the prompt.
13. **Prompt injection?**
    - Four layers (ADR-0007):
      - documents only inside `<document>` tags, as data;
      - forged tags in documents, questions and history neutralised;
      - citations validated, and links reported, never fetched;
      - the model has no tools, network or secrets.
    - A poisoned document was not followed in M5.
    - It can't be fully prevented, so the design limits the damage to one answer.
14. **Multi-turn?**
    - The newest 50 messages are loaded and the history is trimmed to a budget.
    - Follow-ups are rewritten into a standalone query by a rule by default; the LLM rewrite
      is optional (ADR-0009).
    - `rewritten_query` is returned in the `sources` event. Message order is made monotonic
      to survive clock steps.
15. **HyDE, multi-query, contextual retrieval?**
    - HyDE and multi-query fix paraphrase recall; contextual retrieval fixes ambiguous chunks.
    - None was built: the failure analysis found every missed gold chunk already in the dense
      top 40. Ranking and context use were the problems, not recall.
    - Each adds LLM calls (30-90 s each on this CPU). Notes in `m10-techniques.md`.
16. **Agentic RAG, GraphRAG, fine-tuned embeddings?**
    - Agentic for multi-hop (7 multi-chunk dev questions here; 3B tool use is unreliable).
    - GraphRAG for corpus-wide "global" questions.
    - Fine-tuning for specialised vocabulary, which needs far more than 60 labels.
    - None was built (`m10-techniques.md`).
17. **Tables, scans, images?**
    - pymupdf4llm turns PDF tables into Markdown text.
    - Scanned or image-only PDFs fail with "No extractable text" (no OCR).
    - Images aren't indexed.
18. **When is RAG wrong?**
    - A small corpus that fits the context.
    - Tasks that need reasoning over everything (totals, trends).
    - Pure actions.
    - Here the 4096-token local context makes long-context stuffing impossible anyway.
19. **Keeping the index fresh?**
    - Re-processing a document re-chunks it with deterministic ids. Upserts overwrite, and
      `delete_stale` removes the chunks that are gone.
    - The document is hidden until it's `ready` again (a gap rather than stale answers).
20. **Idempotent ingestion?**
    - Chunk id = uuid5(namespace, `document_id:chunk_index`), so a retry overwrites the same
      points.
    - Transient Qdrant errors retry 3 times, then mark the document failed (tested).
21. **What to monitor?**
    - JSON logs with `request_id`/`tenant_id`, and per-answer query traces: stage latencies,
      candidate ids and scores, model, error code.
    - Feedback thumbs; the refusal rate; rate-limit 429s; worker failures.
22. **Cost and latency?**
    - The reranker (38 s) and generation (120 s) dominate on CPU.
    - Levers: a GPU or a hosted model; a smaller rerank window; the refusal short-circuit
      (no chunks, no LLM call); per-tenant and per-user token buckets; a concurrent-answer
      cap and a deadline.
23. **Long context vs RAG?**
    - Retrieval wins on cost, latency, freshness, access control and citing.
    - Long context works for small corpora that fit; this local model has 4096 tokens.
24. **Streaming and disconnects?**
    - SSE events: `sources`, `token`, `done`, `error` (ADR-0008).
    - A total deadline and a generic error event. In a conversation, an answer cut short by
      an error or a disconnect is stored with `truncated=true`.
25. **10,000 tenants?**
    - One collection with the `is_tenant` payload index.
    - Large tenants go to their own collection.
    - A connection pool and read replicas for Postgres; more workers.
    - Keep the per-tenant rate limits.
    - Add RLS as a second lock, and a scheduled trace purge (deferred today).

## Claude Code question bank (M11.7), from how this project was built

The repo's setup: `CLAUDE.md` (layer rules, tenant rule, conventions, "Do NOT" list) and
`.claude/settings.json`.
- **Permissions:**
  - allow: `make`, `pytest`, `ruff`, `mypy`, read-only git, `docker compose ps/logs`;
  - deny: `rm -rf*`, `git push*`, reading `.env`.
- **Hooks:**
  - PreToolUse `guard.py`: blocks edits to `.env` and committed migrations;
  - PostToolUse `ruff_fix.py`;
  - Stop `test_gate.py`: won't end a turn while `make test` fails.
- **Subagents:** `security-reviewer` (read-only tools) and `rag-debugger`.
- **Skill:** `test-writer`. **Commands:** `add-endpoint`, `pr`.

1. **An unfamiliar 100k-line codebase?**
   - Read-only exploration first, then a plan, then small diffs with tests as the gate.
   - Here every step was "tests first, small Conventional Commit, `make lint` / `test` /
     `test-int` before each commit".
2. **Stopping a large unreviewed change?**
   - Permissions (no push, no `rm -rf`), hooks (protected files, the test gate), one logical
     change per commit, and human approval of plans.
   - Every design trade-off was put to me as a question.
3. **CLAUDE.md vs command vs skill vs subagent vs hook?**
   - CLAUDE.md for standing rules.
   - Commands for repeatable prompts (`add-endpoint`).
   - Skills for packaged know-how loaded when relevant (`test-writer`).
   - Subagents for isolated context or tools (`security-reviewer`).
   - Hooks for rules that must always hold.
4. **Hook vs prompt?**
   - A prompt can be forgotten or overridden; a hook runs every time.
   - Editing a committed migration or `.env` is blocked by `guard.py`, not by asking nicely.
5. **Hook exit codes and stdin?**
   - The hook gets the tool call as JSON on stdin.
   - Exit 0 allows; exit 2 blocks, and stderr is fed back to the model.
   - `guard.py` reads `tool_input.file_path`.
6. **Subagents and context isolation?**
   - The security reviewer reads a diff range with only read tools and returns findings,
     without filling the main context.
   - Its 6 reviews (M4-M9) found 3 high and 11 medium issues, all fixed with tests first.
7. **Worktrees vs subagents?**
   - Worktrees give parallel, isolated branches for edits; subagents give isolated context.
   - Not used here: one heavy process at a time on one laptop. Say so.
8. **MCP vs REST, and securing it?**
   - MCP is a protocol for agents to discover and call tools; REST is the API it wraps.
   - Mine (`app/mcp_server`) has two read-only tools over stdio, with a tenant-bound,
     read-only, revocable, hashed API key.
   - No tenant argument; https or localhost only; excerpts framed as data.
   - Demo: a key DELETE gets 403.
9. **Long sessions and context?**
   - The project ran across many sessions with compaction.
   - State lives in files, not in context: `docs/PROGRESS.md` after every step, ADRs,
     `eval-log.md`.
10. **Recovering from a bad multi-file change?**
    - Small commits make `git` the undo; `/rewind` within a session.
    - Here, failures stop the work: the log is saved to `~/nexus-rag-test-logs/` and nothing
      is committed.
11. **Headless use and CI risks?**
    - Headless (`claude -p`) could run reviews in CI. The risks: secrets in context,
      over-broad permissions, unreviewed writes.
    - Not used here; CI runs only lint and tests (and is unverified on GitHub).
12. **Rolling out to 30 people?**
    - Commit the shared `CLAUDE.md`, settings, hooks, agents and skills (as here).
    - A deny list for destructive commands; required review; a short guide.
13. **Cost?**
    - A smaller model for narrow subagents (the security reviewer runs on `sonnet`).
    - Plan before editing; compact long sessions.
14. **Over-reliance risks?**
    - Plausible-but-wrong output. The security reviewer once claimed there was no
      chunk-overlap validator; checking showed it exists and is tested.
    - Also: scope creep and skill atrophy.
    - Mitigations: tests, review, and re-reading auth, retrieval, chunking and isolation code.
15. **Vibe coding?**
    - No. Hypotheses were written before every experiment, with decision rules fixed in
      advance.
    - "Didn't help" results were recorded (M10) and failures were stopped on, not retried.
    - Every number is in a committed file.

## STAR stories (outlines to rehearse; two minutes each)

1. **A bug the agent introduced, caught by review.**
   - **S:** M5 answer generation; the citation parser was agent-written.
   - **T:** ship streaming answers safely.
   - **A:** the `security-reviewer` subagent flagged the citation regex as high severity:
     quadratic on whitespace. I reproduced it (40k spaces took 9.25 s) and fixed it tests
     first with bounded, linear patterns (`951279c`).
   - **R:** linear on hostile input. On 2026-10-13 the five hostile-input tests moved to an
     n vs 4n check that catches quadratic code (13.6x-16.9x) without flaking on a slow
     machine.
   - **Learned:** model output is hostile input too.
2. **A data-driven decision.**
   - **S:** rerank on or off (M8).
   - **T:** choose a final retrieval configuration on dev.
   - **A:** compared E2 and E3:
     - rerank lifted paraphrase R@3 from 4/10 to 8/10;
     - it dropped multi-chunk MRR from 0.719 to 0.401;
     - it costs about 38 s per query.
   - **R:** kept rerank on (ADR-0012), with the cost stated. Later, weighted RRF (M10-1)
     moved 2 questions and was not adopted, by a rule fixed before the run.
   - **Learned:** decide the rule before you see the number.
3. **A disagreement with the agent's plan: to fill in from your own memory.**
   - The record shows the decisions you made where the agent proposed otherwise or asked:
     - the timing-test fix: you required a relative n-vs-4n check instead of a higher limit;
     - stopping on a sleep-interrupted test run, with no silent retry;
     - read-only API keys;
     - refunding 422s from the rate limit.
   - Your reasons are not in the files; tell it in your own words, and only what happened.

## What didn't work (and what it taught)

- **The LLM judge** (ADR-0011):
  - llama3.2:3b agreed with 15 hand grades less often than a constant: correctness 7/15 vs
    10/15, faithfulness 8/15 vs 10/15;
  - it scored all 3 unanswerable questions 0, including 2 exact correct refusals, and never
    listed an unsupported claim.
  - So it isn't used: deterministic checks and hand grades instead.
- **Weighted RRF** (M10-1):
  - dense weight 1.5 or 2.0 gave R@5 31 -> 32/41, R@10 34 -> 35/41, MRR 0.635 -> 0.639; only
    q006 and q015 moved.
  - With rerank on, fusion only chooses the reranker's window. Not adopted.
- **The quote-then-cite prompt** (M10-2):
  - cites-gold 15/40 -> 21/41 and uncited 6 -> 0;
  - but exact correct refusals 4/7 -> 0/7, because the model wrote a Quote: line even when
    refusing. Not adopted.
- **Refusal-first quote-then-cite** (M10-3):
  - refusals 5/7;
  - but 26/39 answers were a bare quote, false refusals 1 -> 2, and cites-gold 18/39.
  - It failed 2 of 4 pre-set conditions (ADR-0016). The lesson: a 3B model follows one
    format rule at a time.
- **Clock-step bugs** (WSL2/Docker clock stepping back):
  - **JWT `iat` failures:** about 1.4 s back every ~30 s caused intermittent 401s; fixed
    with a 5 s leeway (ADR-0006).
  - **Message order:** a 0.65 s step put an answer before its question, so follow-ups lost
    history; fixed with a monotonic `created_at` under a row lock (ADR-0009).
  - **A load-sensitive timing test:** 1.09 s vs a 1.0 s limit; fixed with a relative check.
  - **A test-int run broken by the laptop sleeping 19 minutes:** caught by comparing the
    wall clock with uptime, reported, and rerun cleanly plugged in.
- **A fresh clone found a real bug:** 0600 model-cache files gave "Permission denied" in the
  container. `make fetch-models` now fixes them (`1ee06cb`).
- **The demo's own answer was uncited** (`docs/demo.md`, step 4): the measured 6/40
  weakness, shown as is.
