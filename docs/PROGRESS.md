# Progress: Nexus RAG Build-Along

Checklist of everything left from `docs/guide.pdf` (rest of M4 through M11), plus open items.
Updated at the end of every milestone. Each milestone ends with `make lint`, `make test` and
`make test-int` green, then small Conventional Commits. Nothing is pushed.

Legend: `[x]` done and verified · `[ ]` to do · `[?]` needs your decision · `[~]` partly done

## Baseline (verified 2026-10-08, HEAD `abfdf68`, clean tree)

- `make lint`: ruff, format, mypy --strict, import-linter (3 contracts kept): **pass**
- `make test`: **167 passed**
- `make test-int`: **96 passed** (Postgres/Qdrant/Redis up via `make up`)
- Local model cache (`data/fastembed_cache`): bge-base-en-v1.5 (Qdrant ONNX, quantized), bm25,
  bge-reranker-base. No other models present.

## M4 close (verified 2026-10-08, HEAD `3c502f8`)

- `make lint`: **pass**. `make test`: **202 passed**. `make test-int`: **115 passed**, first
  run, run alone.
- The intermittent `make test-int` failure that `ed64212`'s message mentions did not appear.
  The note that described it was lost in the crash (this file was untracked until M4 closed).
  If it shows up again, capture the full output before any retry.

## Audit findings (new, not in your list)

- [x] `pyproject.toml` restored and `uv.lock` regenerated (`ed64212`). The lock had listed
  only the phase-1 deps, so a fresh clone could not reproduce `.venv`.
- [x] Unused `tenant_header_name` setting removed, with a test that Settings has no tenant
  field (`2b8e01b`).
- [x] `.importlinter` forbids `fastembed` outside `app/providers/` (`f05c318`).

## Open items (your list)

- [x] Standalone pure `rrf(ranked_lists, k=60)` in `app/services/fusion.py`, ties broken by
  id, one count per list; `retrieval.fuse_rrf` delegates to it. Hand-computed tests in
  `tests/unit/test_fusion.py` (`12c491c`).
- [x] Failed-duplicate upload: reset to `uploaded`, re-enqueue, 202 (`4e23c6e`). Tested in
  `tests/integration/test_documents.py:237`.
- [x] Enqueue failure after commit: mark failed, 503 (`bbf9a58`). Tested in
  `test_documents.py:298` and `:316` (re-queue path).
- [x] `.importlinter` forbids pymupdf, pymupdf4llm, trafilatura outside providers (`04c6543`).
- [x] `docs/decisions/dependencies.md` rows for the phase-1 packages and dev tools (`f9bdc96`).
- [x] `.claude/agents/security-reviewer.md`: read-only tools, file:line + severity
  (`6fe2617`).
- [x] Real-tokenizer integration test asserting chunks <= 510 tokens:
  `tests/integration/test_bge_tokenizer.py:18`.

## M4: Retrieval (finish)

- [x] Isolation tests, dense/sparse candidates, tenant-filtered Postgres fetch, reranker
  provider (fastembed cross-encoder), `POST /v1/search` with `extra="forbid"`, debug trace,
  Stop-hook test gate, rag-debugger agent (`abfdf68` and earlier).
- [x] 4.3 Pure `rrf()` (`12c491c`, see open items).
- [x] 4.5 Switches as settings and request params: `RETRIEVAL_MODE=dense|sparse|hybrid`,
  `RERANK`, `CANDIDATES` (default 40, range 1-100), `EXPAND=none|neighbors`. A request value
  overrides the setting; `tenant_id` is still a 422 (`66a9478`, ADR-0003).
- [x] 4.5 Neighbor expansion: `chunk_index` +/- 1, same tenant and document, via
  `chunk_repository.fetch_neighbors` (`cdc8535`, `66a9478`). `EXPAND=parent` is not accepted
  until parent-child chunking lands (M8 E9).
- [x] 4.6 security-reviewer subagent on `abfdf68..66a9478`: no critical, high or medium
  findings. Its coverage gap (cross-tenant search tested only with default switches) is now
  closed by a parametrized test across 5 switch combinations, checked to fail with the Qdrant
  tenant condition removed (`3c502f8`). Low and info items are under "Review follow-ups".
- [x] 4.7 Eyeball on `sample_docs/`: four queries in four modes, real output pasted in
  `docs/decisions/retrieval-observations.md` (`4a96b4b`). Main finding (hypothesis for M8):
  on a 29-chunk tenant, plain RRF moves dense's rank-1 hit for a paraphrase down to rank 9;
  rerank brings it back to rank 2.
- [x] Decision: the API keeps `limit` where the guide says `top_k` (already shipped and
  tested).
- [x] `make test-int` green on the M4 head (115 passed).

### Review follow-ups (from 4.6, not blocking)

- [ ] LOW: `rerank=true` + `candidates=100` lets any user run a 50-pair cross-encoder pass
  per request with no rate limit. Covered by the M7 7.2 per-tenant rate limiter; consider a
  concurrency cap around rerank there too.
- [?] LOW: `fetch_chunks` and `fetch_neighbors` don't filter on document status, so chunks of
  a document that is being re-processed can still be returned. Not a tenant leak. Should
  non-`ready` documents be hidden from search? You decide.
- [?] INFO: `debug=true` is open to every authenticated user. The trace holds only own-tenant
  chunk ids, scores and timings. Admin-only? You decide (affects the M8 runner).
- [ ] Missing tests the reviewer named: `expand=neighbors` with `document_ids` never attaches
  neighbors from another document; a unit assertion that `fetch_neighbors` receives the
  caller's tenant_id; `candidates=101` gives 422 at the HTTP level.
- Not acted on: the reviewer flagged a possible E501 in `app/api/search.py`, but
  `make lint` passes, so that was a false positive.

## M5: Generation, streaming, citations

- [ ] 5.1 ADR: prompt design, SSE event schema, citation validation, injection mitigations.
- [ ] 5.2 `app/providers/llm.py`: `LLMProvider` Protocol (`stream`, `complete`, `name`). It has:
  - `FakeLLM` (scripted tokens) for tests.
  - `OllamaProvider` over HTTP (`OLLAMA_URL`, `OLLAMA_MODEL`) using httpx, not an extra SDK.
  - `AnthropicProvider` (anthropic SDK). It's built only when `LLM_PROVIDER=anthropic` and
    `ANTHROPIC_API_KEY` is set; otherwise it's a startup error, never a silent call. Its tests
    are skipped without the key.
  - `get_llm()` factory.
  New deps: `anthropic`, and `httpx` moves to runtime. Both explained in chat first.
- [?] Ollama model choice and pull. That's a model download, so I'll ask at M5 start.
- [ ] 5.3 `app/prompts/rag_system.md` and the user template, loaded at runtime. Add a CLAUDE.md line:
  prompts live in `app/prompts/`.
- [ ] 5.3 `app/services/generation.py` pure functions: `build_messages` (context budget
  `MAX_CONTEXT_TOKENS`, best-first) and `parse_citations` (`[1]`, `[1][3]`, `[2, 3]`,
  out-of-range numbers stripped and counted). Snapshot test of the rendered prompt; poisoned
  source rendered verbatim inside its tag.
- [ ] 5.4 `POST /v1/chat` (SSE): events `sources` -> `token`* -> `citations` -> `done`, and `error`.
  JSON `data:`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, stops on disconnect.
  Empty retrieval refuses with zero LLM calls. Tests use FakeLLM: event order, a newline inside a
  token, the refusal path, invalid citation stripped, tenant isolation in `sources`, 401, 422.
- [ ] 5.5 Manual run against Ollama: answerable, unanswerable and poisoned documents. Report
  observations as written.
- [ ] security-reviewer subagent on the M5 diff; fix medium+ findings with tests.

## M6: Conversations, memory, query rewriting

- [ ] 6.1 New migration: `conversations`, `messages` (index `(conversation_id, created_at)`).
  Repositories scoped by `tenant_id` AND `user_id`.
- [ ] 6.2 `app/services/rewriting.py`: `rewrite_query` (skip on first turn; fall back on empty or
  >3x-length output; prompt in `app/prompts/rewrite.md`) and `trim_history(messages, max_tokens)`.
  Tests use FakeLLM.
- [ ] 6.3 Five conversation endpoints. The messages endpoint reuses the M5 chat pipeline
  (shared service), persists the user message first and the assistant message on completion
  (`truncated=true` on disconnect), and puts `rewritten_query` in the `sources` event.
- [ ] 6.4 IDOR suite: other user in the same tenant gets 404, other tenant gets 404, list shows
  only own, rewrite never crosses tenants, delete cascades messages.
- [ ] 6.5 `.claude/commands/pr.md` (prints PR text only, never pushes).
- [ ] security-reviewer subagent on the M6 diff.

## M7: API polish and CLI

- [ ] 7.1 API audit done in-session (not `claude -p`, to keep cost at zero), written to
  `docs/api-audit.md`.
- [ ] 7.2 RFC 9457 problem+json handlers and request-id middleware (contextvar, echoed
  `X-Request-ID`, 500 without stack trace).
- [ ] 7.2 Cursor pagination (opaque, tenant-scoped, invalid cursor gives 422, capped limit) on
  documents, chunks and conversations.
- [ ] 7.2 Per-tenant Redis token-bucket rate limiter (reads vs `/chat`), 429 + `Retry-After` +
  `X-RateLimit-*`. Fake-clock unit tests and a real-Redis integration test (no fakeredis dep).
- [ ] 7.2 Optional `Idempotency-Key` on `POST /v1/documents`.
- [ ] 7.3 OpenAPI pass: tags, summaries, examples, error responses, unique operation_ids. Export
  `openapi.json`.
- [ ] 7.4 `cli/nexus_cli.py` (typer + httpx): login, upload --wait, docs, search, ask
  (SSE), history. Token stored in `~/.nexus/config.json` with mode 0600. Pure SSE-line parser
  tests. New dep: `typer`.

## M8: Evaluation and tuning

- [?] 8.1 Corpus choice (15-25 docs) and an eval tenant. You choose.
- [?] 8.2 `eval/tools/gen_candidates.py` and `eval/tools/review.py`. I draft candidates; **you review
  and approve every question** (keep/edit/reject), rewrite about a third, and add exact-token,
  multi-chunk and 8+ unanswerable questions. Test: every gold span occurs in its document.
  Hold out ~20%.
- [ ] 8.3 `eval/metrics.py`: is_hit, recall@k, precision@k, MRR (0.444 example), nDCG@k, with
  hand-computed tests.
- [ ] 8.4 `eval/judge.py` and `eval/prompts/`: claim-level faithfulness, 0-1-2 correctness, refusal
  detection. Calibration tool where **you** hand-grade 15 answers. A local judge is reported as rough.
- [ ] 8.5 Migration 3 (`eval_runs`, `eval_results`), `eval/runner.py` with `--set` overrides,
  config and git SHA recorded. Endpoints under `/v1/eval/*` (admin, async via Celery).
  `nexus eval run`.
- [ ] 8.5 `.claude/commands/run-eval.md`, `.claude/skills/eval-report/SKILL.md`, analyst subagent.
- [ ] 8.6 Experiments E0-E3 and the chunk-size sweep at minimum (E4-E10 as time allows), each
  with its hypothesis written first in `docs/decisions/eval-log.md`. Include the 4.7
  hypothesis: plain RRF hurts paraphrases when the sparse list is short and the dense list
  covers the whole tenant (try weighted RRF, and `CANDIDATES` well below the corpus size).
- [ ] 8.6 Parent-child chunking (enables `EXPAND=parent`, E9).
- [ ] 8.7 Failure buckets A-G, fix the largest bucket, re-run, one ADR per decision. Only
  measured numbers.

## M9: Observability, MCP server, CI/CD, hardening

- [ ] 9.1 JSON structured logs (request_id, tenant_id; no document content). `span()` tracing
  helper. Migration 4 `query_traces`. `POST /v1/messages/{id}/feedback` and
  `GET /v1/traces/{request_id}` (cross-tenant gives 404).
- [ ] 9.2 `app/mcp_server/` (official MCP SDK): read-only `search_documents` and
  `list_documents`, no tenant argument, thin adapter over the REST API, capped output, stderr-only
  logs. Subprocess JSON-RPC tests and a test that no schema has tenant_id. New dep: `mcp`.
- [ ] 9.3 `.github/workflows/ci.yml` (lint, unit, integration with service containers, docker
  build), `eval-smoke` workflow, pre-commit with ruff. CI can't run here, so it will be
  reported as unverified until you push.
- [ ] 9.4 Multi-stage Dockerfile (non-root, pinned base, HEALTHCHECK, model cache as a
  volume), `.dockerignore`, compose `app` profile. Pulling a base image is a download, so I'll
  ask first.
- [ ] 9.5 README (only verifiable facts, TODO for anything unmeasured) and `docs/security.md`
  (controls with file:line and the proving test).
- [ ] security-reviewer subagent on the M9 diff.

## M10: Advanced RAG lab (at least two builds behind flags, evaluated)

- [?] Which two (or more) to build: contextual retrieval (`CONTEXTUALIZE`, new migration for
  `chunks.context`), `QUERY_TRANSFORM=multi|hyde`, or agentic mode. Decide after M8, using
  the numbers.
- [ ] Each one evaluated against the M8 baseline with cost and latency. "Didn't help" is recorded
  honestly.
- [ ] Semantic caching: design note only (tenant-scoped key, invalidation), unless the data shows
  repeated queries.
- [ ] Short notes on the techniques the guide says to know without building (M10.6).

## M11: Packaging

- [ ] `docs/interview/`: resume bullets (only measured numbers, TODO otherwise), two-minute
  pitch, five-minute demo script, whiteboard notes, scale-up numbers. Question banks and STAR
  stories are outlines; you rehearse them.
- [ ] Final check: README and demo work from a fresh clone.
