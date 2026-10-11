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

## Intermittent 401 in integration tests (fixed 2026-10-08, `5d46126`, ADR-0006)

- [x] Cause: the WSL wall clock steps back about 1.4 s every ~30 s, and PyJWT rejected
  `iat > now` with zero leeway. A unit test reproduced it before the fix
  (`ImmatureSignatureError: The token is not yet valid (iat)`).
- [x] `JWT_LEEWAY_SECONDS` (default 5, range 0-60). A token expired by 10 s and an `iat` 30 s in
  the future are still rejected.
- [x] `make test-int` after the fix, run alone: **142 passed** in 135 s (several clock steps
  inside the run), no 401. `make test`: **208 passed**.

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
- [x] Search returns only chunks of `ready` documents, filtered in
  `chunk_repository._searchable`; `limit` is still filled (`6eb3ca7`, ADR-0004).
- [x] `debug=true` is admin-only; a non-admin gets 403 (`0f10c7d`, ADR-0005).
- [ ] Missing tests the reviewer named: `expand=neighbors` with `document_ids` never attaches
  neighbors from another document; a unit assertion that `fetch_neighbors` receives the
  caller's tenant_id; `candidates=101` gives 422 at the HTTP level.
- Not acted on: the reviewer flagged a possible E501 in `app/api/search.py`, but
  `make lint` passes, so that was a false positive.

## M5: Generation, streaming, citations (closed 2026-10-09)

- [x] 5.1 ADR-0007 prompt-injection defence, from your four layers (`35cd4ba`). The SSE schema
  goes in the 5.4 ADR.
- [x] 5.2 LLM providers (`6061bfa`, `efcb960`, `a58e7bf`, `bcd3b17`):
  - `LLMProvider` Protocol (`stream`, `complete`, `name`) and `FakeLLM`; typed errors.
  - `OllamaProvider` (httpx, NDJSON) and `AnthropicProvider` (httpx, SSE, no SDK), sharing
    one retry on 429/5xx (`llm_http.open_stream`).
  - Anthropic: `claude-opus-5-5`, refusal fallback `"default"` on, no temperature (rejected by
    the model), `max_tokens` raised to 16000 because thinking counts toward it.
  - `LLM_PROVIDER=anthropic` without a key fails at startup; `build_llm` refuses too.
  - httpx moved dev -> runtime, logged in `dependencies.md`. All tests use `MockTransport`.
- [x] Ollama 0.40.2 and `llama3.2:3b` installed inside WSL (by you).
- [x] Dependencies: option B, no anthropic SDK. `AnthropicProvider` uses our own httpx.
- [x] 5.3 `app/prompts/rag_system.md` and `rag_user.md`, loaded at runtime by `load_prompt`;
  CLAUDE.md line added (`48b9362`).
- [x] 5.3 (`6061bfa` LLMProvider + FakeLLM, `da68456`) `app/services/generation.py` pure functions: `build_messages` (context budget
  `MAX_CONTEXT_TOKENS`, best-first) and `parse_citations` (`[1]`, `[1][3]`, `[2, 3]`,
  out-of-range numbers stripped and counted). Snapshot test of the rendered prompt; poisoned
  source rendered verbatim inside its tag. Four attack documents, checked to fail when the
  neutraliser or the citation range check is disabled.
- [x] 5.4 `POST /v1/chat` (SSE), ADR-0008 (`129b27a`, `eb5213c`, `6e0ecaf`, `1f2b4e6`):
  sources -> token* -> citations -> done (or error); JSON `data:`, `no-cache`,
  `X-Accel-Buffering: no`; disconnect closes the LLM stream; empty retrieval refuses with zero
  LLM calls. Tests: event order, newline in a token, refusal, invalid citation stripped,
  tenant isolation in `sources`, 401, 422 (incl. `tenant_id`), 503 without an LLM.
- [x] 5.5 Manual run against Ollama `llama3.2:3b` (CPU only), raw streams and timings in
  `docs/decisions/generation-observations.md`:
  - Q1 answerable, cold: **timed out** (`llm_unavailable`, 181.51 s). Cold load plus a
    1,348-token prompt at ~15 tokens/s took longer than `LLM_TIMEOUT_SECONDS=120`. Repeated
    warm: correct and cited `[1]`, 33.77 s (Ollama's prompt cache helped).
  - Q2 unanswerable: refused with the exact refusal text, 92.78 s.
  - Q3 poisoned: injection **not** followed, but the format was ignored: prompt scaffolding
    echoed, answer right but uncited, 66.92 s.
  - Rerank takes ~23 s for 30 pairs on this CPU, with or without Ollama loaded.
- [x] security-reviewer subagent on `7d2986c..1f2b4e6`: 1 high, 3 medium, all fixed with tests
  first (`951279c`, `3b108de`, `9e3fd25`):
  - HIGH: quadratic citation regex (40k spaces: 9.25 s, measured) -> bounded, linear.
  - MEDIUM: 5000-digit citation raised mid-stream -> citations are 1-4 digits.
  - MEDIUM: no catch-all / total deadline / safe close -> generic error event,
    `LLM_ANSWER_DEADLINE_SECONDS`, shielded `aclose()`.
  - MEDIUM: cost exposure -> `CHAT_MAX_CONCURRENT_ANSWERS` busy cap now; the per-tenant quota
    is the M7 7.2 rate limiter.
  - Lows fixed: NaN/negative `retry-after`, https base URL in production, fullwidth and
    zero-width tag lookalikes. Not fixed (info): one retry may double-bill if the first call
    was processed; provider JSON error text isn't length-capped in logs.
- [x] M5 close checks (after 5.5, Ollama stopped, run one at a time): `make lint` pass,
  `make test` **295 passed**, `make test-int` **155 passed**, no 401.
- For M8 (from 5.5): CPU rerank and prompt processing dominate latency; 120 s LLM timeout is
  too short for a cold CPU start; measure citation-format adherence of the 3B model; consider
  stripping echoed `<document>`/`<question>` scaffolding from answers.

## Between M5 and M6 (2026-10-09)

- [x] `done.answer` strips echoed `<document ...>`/`<question>` wrappers, tested with the exact
  Q3 output (`b718299`).
- [x] `OLLAMA_TIMEOUT_SECONDS=300` (Ollama only), `LLM_ANSWER_DEADLINE_SECONDS` 180 -> 420
  (`c2f9e9d`). A cold start under the new limits isn't re-measured yet.

## M6: Conversations, memory, query rewriting (closed 2026-10-09)

Your decisions (2026-10-09): rewriting `REWRITE_MODE=rule|llm|off`, default `rule`, both built;
history shares `MAX_CONTEXT_TOKENS` (2500), capped at `HISTORY_MAX_TOKENS=500`, most recent
first; conversations are owner-only (admins get 404 too).


- [x] 6.1 Migration `7043f21d7f44` (new file; read back, 2 risks fixed: enum dropped on
  downgrade, composite FK so a message can't name another tenant) and a repository scoped by
  `tenant_id` AND `user_id` (`2413ceb`, `8cb2fc5`). Ownership tests written first; removing
  either the user_id or the tenant_id condition fails 4 tests each.
- [x] 6.2 `rewriting.py`: `trim_history` and `rewrite_query` with `REWRITE_MODE=rule|llm|off`,
  prompt in `app/prompts/rewrite.md`, FakeLLM tests (`c2561da`, `be8d156`, ADR-0009). Deviation
  from the guide: the overlong limit is 3x (previous + current question), not 3x the question.
- [x] 6.3 Five conversation endpoints reusing the M5 pipeline (`098efd3`, `335344b`,
  `f2e0a2a`, `6ebae2d`): user message saved first, assistant saved however the stream ends
  (`truncated=true` on error or disconnect), `rewritten_query` in `sources`. Stored sources
  keep ids/headings, never chunk text. Fix found in the 6.5 run: SQL NULL for missing
  sources/usage (`c87228b`).
- [x] 6.4 IDOR suite (`53b7316`), written before the endpoints, owner-200 precondition in
  each test: other user, tenant admin and other tenant get the same 404 as a missing id for
  get/post/delete, nothing written; list own only; cascade; rewrite never crosses tenants;
  401 everywhere. Mutations caught: no user_id in ownership (6 fail), in list (2), route's
  404 skipped (3).
- [x] 6.5 `.claude/commands/pr.md` (`202b9b6`), base `master`; not run end to end (slash
  commands can't be invoked from here). Two real turns against Ollama recorded in
  `generation-observations.md` (`055e53e`): the rule rewrite resolved "them", cold turn 1
  finished at 224.93 s under the new 300 s timeout.
- [x] security-reviewer subagent on `88b4b21..1668dbd`: no critical/high, 3 medium, all fixed
  with tests first:
  - MEDIUM-1: shared 404/401 exception grew its traceback per raise (reproduced, depth
    2 -> 10) -> fresh exception per raise, incl. the pre-existing auth 401 (`6acb207`).
  - MEDIUM-2: LLM rewrite ran outside answer slots and deadline -> now inside (`d96450c`).
  - MEDIUM-3: unbounded loads/growth -> newest-50 history load, paged messages, 409 caps
    (`223c9d9`).
  - Lows/infos fixed: vanished conversation -> 404 (`78cab77`); answered pairs only, stale
    `[N]` stripped, "earlier turns are context" rule, one-line rewrite history, cleaned
    partial saves (`da19edc`); provider errors logged by type (`a801afa`); `/pr` exact
    tools (`bcafe01`).
  - Accepted, in ADR-0009 (`d28d0b8`): document text can survive in old answers after the
    document is deleted; no composite FK `conversations(user_id, tenant_id)` yet (needs a new
    migration).
- [x] M6 close checks (run one at a time, Ollama stopped): `make lint` pass, `make test`
  **365 passed**, `make test-int` **218 passed**, no 401, nothing flaky.

## M7: API polish and CLI (closed 2026-10-10)

Your decisions (2026-10-09): ADR-0009 accepted as written (3x rewrite rule), caps stay at
1000. Rate limiter in **Redis**, token buckets **per tenant and per user** (user = half the
tenant limits), keyed only from the verified token. Limits per tenant: chat (`/v1/chat` and
conversation messages) 5 burst then 1/min; search 20 then 1/5 s; other routes 120 then 2/s.
Fail closed on LLM routes and open on reads when Redis is down. CLI with **argparse** (no new
dependency).


- [x] 7.1 API audit in-session from `app.openapi()` and the routers: 9 findings and an ordered
  plan with risks in `docs/api-audit.md`.
- [x] 7.2 RFC 9457 problem+json handlers and request-id middleware (`b10c839`): every 4xx/5xx
  incl. unknown routes and unhandled errors; safe incoming ids echoed, others replaced; ids
  on every log record; 422s list errors without echoing input.
- [x] 7.2 (added) Migration `3ccf8af42a82` (`2ff30a2`): composite FK
  `conversations(user_id, tenant_id)` -> `users(id, tenant_id)`, test first; the upgrade
  refuses on mismatched rows (checked with a probe row). **Incident:** while checking it I
  chained commands after a failed `make migrate`; `alembic downgrade -1` then dropped and
  recreated the `conversations`/`messages` tables in the local dev DB. Lost: test leftovers
  and the M6 6.5 demo conversation (its output is in `generation-observations.md`).
  Documents, chunks, users and Qdrant were untouched.
- [x] 7.2 Cursor pagination (`c8c7ca4`, `88b6fed`): opaque, HMAC-signed, scope-bound cursors on
  documents, chunks, conversations and conversation messages; forged or cross-scope -> 422;
  limits capped; offset removed (4 existing tests moved to cursors).
- [x] 7.2 Rate limiter (`bb11076`, `ec7fb1e`, `3bbb536`): Redis token buckets per tenant AND per
  user, atomic Lua; chat / search / default classes; 429 problem + `Retry-After` +
  `X-RateLimit-*`; token-only keys (spoofed forwarding headers tested); chat fails closed,
  others open. Fake-clock unit tests, real-Redis tests; removing the user bucket fails 8.
  `make test-int` after wiring: 258 passed.
- [ ] 7.2 Optional `Idempotency-Key` on `POST /v1/documents`: deferred (upload already dedups by
  content hash; low value, see `docs/api-audit.md` item 8).
- [x] 7.3 OpenAPI pass (`4118d54`): problem+json error responses everywhere, explicit camelCase
  operation ids, SSE event schemas in components, unversioned auth hidden from the docs;
  `make openapi` -> `docs/openapi.json` with a staleness test and a $ref-resolution test.
  Postman import not run (not possible from here).
- [x] 7.4 `cli/nexus_cli.py` (`b455019`), argparse + httpx (your choice; no new dependency):
  login, logout, upload --wait, docs, search, ask (SSE), history. Token 0600 in a 0700 dir,
  refused if loose, bound to its API URL, https or loopback only, never printed.
  Real run in `docs/cli-demo.md`: everything works; `ask` correct but uncited (162.86 s cold).

- [x] security-reviewer subagent on `42f06f0..89187b2`: no critical; 2 high, 5 medium, all fixed with
  tests first (your decisions for the design ones):
  - HIGH-1: signup/login unlimited, and open signup minted fresh buckets -> per-IP (+
    `TRUSTED_PROXIES`), per-email login and global signup budgets, fail closed (`ec01f5c`).
  - HIGH-2: credential fields unbounded; a >72-byte password was a 500 (bcrypt), reproduced ->
    72-byte limit, extra=forbid (`4da7398`). Unversioned `/auth/*` removed (`1def94e`).
  - MEDIUM: uploads in the cheap bucket -> own class 10/1 per min (`315f962`); no Redis
    timeouts -> 0.5 s, malformed replies handled (`a840235`); CLI config chmod/symlink
    (reproduced), terminal escapes, login target, redirects/tracebacks (`ec9f507`).
  - LOW fixed: SQL parameters in error text/logs -> hide_parameters (`bccf679`).
  - [x] Your decision: a 422 is refunded, 401/403 are not (ADR-0010, see the M8 section).
  - Accepted, in ADR-0010 (`0097493`): half-share user buckets can drain a tenant; cursor key
    tied to the JWT secret; logout doesn't revoke; public `/docs`.

- [x] M7 close checks (run one at a time, Ollama stopped): `make lint` pass, `make test`
  **479 passed**, `make test-int` **285 passed**, no 401, nothing flaky. Two new cosmetic
  warnings: sync tests in asyncio-marked modules, as in `test_isolation.py`.

## M8: Evaluation and tuning

Your decisions (2026-10-10): corpus = docs/guide.pdf + this repo's ADRs and Markdown docs +
sample_docs 01-05, frozen under eval/corpus/ (PROGRESS.md left out: it repeats the ADRs, so gold
labels would be ambiguous). I draft candidate questions in-session; you approve every one before
any metric runs. Judging: deterministic metrics on every answer (refusal accuracy, citation
validity, reference-fact check) plus a one-call llama3.2:3b judge on a fixed 20-question sample,
calibrated on 15 answers you grade; judge numbers reported as rough. Metrics: Recall@1/3/5/10,
MRR, nDCG@10; generation runs only for E3 and the best config (and the final held-out run).
Free setup only; ask before any run over 30 minutes.

- [x] 8.1 Corpus (your choice) frozen in `eval/corpus/` (22 files, manifest + hash test,
  `0509306`); eval tenant ingested through the API: 22/22 ready in 350 s, 473 chunks.
  Parse findings: guide.pdf code-box text became headings (wrong `heading_path` on many
  chunks), and the guide's example ADR block survives only as a heading (bucket A parse loss);
  generation-observations.md repeats sample-doc text verbatim, so spans can hit in two docs.
- [x] 8.2 Dataset v1 locked (`240fa02`, `eb4fd87`): 60 questions you approved in 3 batches
  (21 factoid, 12 paraphrase, 9 exact-token, 9 multi-chunk, 9 unanswerable; q020 rejected and
  replaced by q061), 63 gold spans, every question with its wording_origin. Hold-out 20%,
  stratified, seed 20261010: 48 dev / 12 hold-out (factoid 4, others 2 each). Tests: v1 shape,
  split reproducible, ids in exactly one split; all 63 spans in the parsed frozen docs.
  Per-type hold-out numbers (n = 2) will be reported as anecdotes, not rates.
- Run-time estimates (scaled from measured rates, not yet measured on this corpus): E0-E2
  (no rerank) about 1 min each on the 48 dev questions; E3 (rerank, up to 50 pairs at
  ~0.77 s/pair, ~38 s per search) about 31 min on dev, over the 30-min line, so it needs your OK;
  one generation run on dev about 1.8-2.7 h (needs your OK).
- [x] 8.3 `eval/metrics.py` with hand-computed tests (`aed8ce0`).
- [x] 8.4 Judge (`389a009`): deterministic checks on every answer (refusal by the exact
  sentence, citation validity + gold support, reference-fact check on numbers/identifiers) and
  a one-call LLM judge (0-1-2 correctness, faithful + unsupported claims; prompts in
  `eval/prompts/`), unreadable verdicts recorded as errors. Fixed 20-question dev sample (seed
  20261010): q006 q007 q008 q012 q015 q018 q021 q022 q024 q027 q030 q034 q035 q036 q044 q046
  q050 q053 q056 q057. Calibration tool (`dbc6696`): you grade 15, agreement with counts.
  FakeLLM only; **the real judge has not been run**. A local judge is reported as rough.
- [x] 8.5a v1 final (`3c488d5`; sha256 pin test `16ae46a`): any change becomes v2. Runner
  `eval/runner.py` (`e8380e3`): `--set mode/rerank/candidates/expand/limit`, `--split dev`;
  `holdout` refused without `--final-holdout`; one line per question flushed as it finishes,
  resumable per `--tag`, changed config refused; run.json has config, dataset, split seed,
  runner seed, git sha + dirty flag, times. Rerank score cache in `eval/state/` (`079cc57`).
  Calls `retrieve()` in-process for the eval tenant (an HTTP run would be paced by the search
  rate limit). Tested with fakes only.
- [ ] 8.5b Migration 3 (`eval_runs`, `eval_results`), `/v1/eval/*` endpoints, `nexus eval run`:
  not started (after the experiments you asked for first).
- [ ] 8.5 `.claude/commands/run-eval.md`, `.claude/skills/eval-report/SKILL.md`, analyst subagent.
- [x] 8.6a E0-E2 on dev (`44bd4d0`, eval-log.md): Recall@10 dense 31/41, sparse 25/41,
  hybrid 34/41; MRR 0.532 / 0.546 / 0.628. Paraphrase weakest everywhere (hybrid 6/10).
- [x] 8.6b E3 hybrid + rerank on dev (`09de946`, 28 min 50 s): R@10 34/41 (E2 34/41), R@1 20/41
  (E2 17/41), MRR 0.635 (E2 0.628). Paraphrase R@3 8/10 (E2 4/10), but multi-chunk MRR 0.401
  (E2 0.719) and factoid R@3 12/17 (E2 15/17). 11 questions up, 12 down. Judge now uses
  `<document>` tags per CLAUDE.md (`cec3af2`, judge never run).
- [x] 8.6c `--generate` path (`5c0c062`): real answer pipeline per question, deterministic checks
  per line, generation counts in summary.json; Ollama only. FakeLLM tests. Approved next: smoke
  test (3 questions), then all 48 dev with E3 config + limit 6. Real judge NOT approved.
- [x] Smoke test (`eval/runs/smoke-gen`): first try exited in 3.6 s, as `make_search` still
  refused --generate (an edit that didn't apply; fixed and covered, `dba1c22`). Then: rerank
  0.0 s (cached), answers 150-229 s; q053 (unanswerable) answered only "[6]", q001 uncited.
  Fact check fixed before the full run (`c8480ae`). Full 48-question dev run: started.
- [x] 8.6d E3-gen complete, 48/48 dev (21 in the first run, stopped by the memory rule; 27 in 3
  batches of 9 with `ollama stop` between). Refusal 4/7 exact; 1 false refusal (q061); 0
  errors; 40 valid citations, 6 answers uncited, 15/40 cite gold; facts all-found 7/23. Format
  problems listed in eval-log.md (bare "[N]" answers, non-numeric/fused brackets, leftover
  `<answer>` tags). My rough reading: 23 right, 9 partial, 8 wrong. Real judge NOT run.
- [x] 8.6e Checks before any change (Ollama stopped): `make lint` pass, `make test` 556 passed.
- [x] 8.6f near_refusal is its own outcome (`211c620`): E3-gen q055 and q058 now count as
  near-refusals, not misses (the old pattern caught neither). The fact check already ignored
  facts the question states (`c8480ae`); q017's flaw is different (its reference holds a fact
  the question doesn't ask for) and isn't fixed.
- [x] 8.6g Calibration ready (`65942dd`, `43ca814` typing): the 15 come from the fixed 20-question
  judge sample with no verdict needed: q007 q008 q012 q015 q018 q021 q022 q024 q027 q030 q034
  q036 q044 q046 q056. You grade; the judge isn't run until you say "run the judge".
- [x] 8.6h Approved and committed, `make lint` and `make test` before each: leftover-tag stripping
  (`77b8d81`, 590 passed), `malformed` citations report + fused-citation space (`38856c1`, 605),
  eval citation check reading `malformed` (`2fd0d15`, 609), `eval/tools/rescore.py` + E3-gen
  `rescore.json` + eval-log entry (`e7c0669`, 613). Then `make test-int` alone, Ollama stopped:
  354 passed. Re-score: near-refusals 2 (q055, q058), missed 1 (q053), correct 4/7 unchanged;
  4 answers with malformed citations. q017's reference problem left alone (would be v2) and
  logged as a known fact-check limitation.
- [x] 8.6i You graded the 15; judge runner `eval/tools/judge_run.py` (`0ac2ae9`, prompt unchanged,
  resumable, a verdict line per call). Judge run on the 20-question sample of the stored E3-gen
  answers: 27 min 34 s, 0/20 unreadable, min available memory 2,697 MB, Ollama stopped after.
  Agreement with your 15: correctness exact 7/15, within 1 14/15, faithful 8/15. A constant "2"
  scores 10/15 exact and a constant "faithful" 10/15, so the judge is worse than a constant.
  It caught 2/5 of your "n" (missed the q012 wrong-source case), gave no unsupported claims in
  any reply, and scored all 3 unanswerables 0 (including 2 exact correct refusals). Rough judge
  scores on 20: correctness 0/1/2 = 3/14/3, faithful 12/8. eval-log.md has the details.
- [x] 8.6j Your decision: the judge is left unchanged and its numbers are not used anywhere
  (ADR-0011: it failed calibration). Headline answer quality = deterministic checks + your 15
  hand grades (n = 15: correctness 0/1/2 = 1/4/10, faithful 10 y / 5 n; per type in
  eval-log.md).
- [x] 8.6k E3-neighbors (`a82573d` scores the expanded text, `07d5647` hypothesis first,
  `3f081aa` result). Same hit order as E3; R@10 34 -> 36/41, MRR 0.635 -> 0.685; multi-chunk
  full R@10 4 -> 5/7, MRR 0.401 -> 0.548; only q006, q046, q050 moved (all up). Tokens/hit median
  172 -> 425; all top-6 fit 2500 in 25/48 (E3 48/48). 4 s (rerank cached). No generation.
- [x] 8.6l E4 approved: sizes 200 and 500, overlap 50, a separate tenant each, no overlap sweep.
  Step a: `CHUNK_MAX_TOKENS` / `CHUNK_OVERLAP_TOKENS` (defaults 350/50, proven unchanged by
  tests, `1fef2e5`) and `eval.runner --state` (`6615707`).
- [x] 8.6m The flaky `make test-int` failure (second turn saw no history) was a real bug: the
  WSL2/Docker clock stepped back ~0.65 s mid-turn, and messages ordered by wall-clock
  `created_at` came back as (answer, question). Reproduced with tests, fixed by a monotonic
  `created_at` under a conversation row lock (your choice; ADR-0009; `76890d9`). One of my new
  tests first reached the real Ollama model (no `fake_llm`); fixed before the final suites.
  Final: `make lint` pass, `make test` 641, `make test-int` 358, 0 Ollama models loaded after.
- [x] 8.6n E4 hypotheses written before any run (`aae89e4`). Then one size at a time, each in
  its own tenant (API and worker up only for ingestion):
  - 200: 664 chunks, ingest 4 min 47 s, retrieval 10 min 51 s.
  - 500: 424 chunks, ingest 6 min 59 s, retrieval 19.0 min of work. Its ~53 min wall time
    includes ~34 min of machine sleep; accepted as is.

  Dev, 41 answerable (200 / 350 / 500):
  - R@1 18 / 20 / 20, R@3 24 / 27 / 26, R@10 34 / 34 / 34;
  - MRR 0.596 / 0.635 / 0.638.

  200 loses early ranks in paraphrase and multi-chunk; 500 ties 350 within noise. Conclusion:
  keep 350. Hypothesis checks and moved questions are in eval-log.md.
- [x] 8.6o Final configuration, your choice from dev only (ADR-0012): hybrid, candidates 40,
  rerank on (E3), expand none, chunks 350/50, chat limit 6. These are the app defaults.
- [x] 8.6p The one hold-out run (retrieval only, `--final-holdout`, ADR-0012 config), 7 min 7 s,
  no alerts. Final, not tuned on: R@1 5/10, R@3 8/10, R@5 9/10, R@10 9/10, MRR 0.670,
  nDCG@10 0.732. Dev E3: 20/41, 27/41, 31/41, 34/41, 0.635, 0.706. Not worse; within noise.
  q051 (multi-chunk) missed. Hold-out refusal accuracy: not run (optional; your call).
- [x] 8.6q M8 summary in README.md (measured numbers only). The three bugs you listed are
  credited to where they were found: message order, a flaky test-int in M8; the refund stub,
  test-int at the M8 start; JWT leeway, M4 integration tests, so not the evaluation. The
  evaluation's own finds are listed separately.
- [ ] M8 items still open from the guide: migration 3 + `/v1/eval/*` + `nexus eval run`;
  `run-eval` command, `eval-report` skill, analyst subagent; failure buckets A-G (8.7);
  parent-child chunking (E9); the M8 security review. Your call which of these close M8.
- `make test-int` first failed with 37 failures (output kept, not retried): every 422 path
  got a 500 because the integration rate-limit stub had no `refund()` since `639b968`; test-int
  had last run one commit before it. Deterministic, not the old 401. Stub fixed (`bdcf7f9`):
  `make lint` pass, `make test` 545 passed, `make test-int` 354 passed.
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
