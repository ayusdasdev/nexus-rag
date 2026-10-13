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

## M8: Evaluation and tuning (closed 2026-10-11)

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
- [-] 8.5b Migration 3 (`eval_runs`, `eval_results`), `/v1/eval/*` endpoints, `nexus eval run`:
  deferred to Later (your decision, 2026-10-11).
- [-] 8.5 `.claude/commands/run-eval.md`, `.claude/skills/eval-report/SKILL.md`, analyst subagent:
  deferred to Later.
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
- [x] 8.6r M8 security review (security-reviewer subagent on `8a08713..HEAD`): no critical,
  high or medium findings, so nothing to fix. Low and info items were listed for you:
  - 422 refunds leave invalid requests unmetered (not a bypass of the chat cost limit);
  - committed `run.json` files hold the eval tenant id, and the hold-out one an absolute
    local path;
  - `ingest_corpus --password` is visible in `ps`;
  - the eval "Ollama only" guard doesn't pin `OLLAMA_URL` to loopback;
  - the lock relies on READ COMMITTED (info);
  - a 64-token minimum chunk raises the embed cost (info).

  One reported low (a stray leading space in `_strip_leftover_tags`) was checked and is not
  a bug: `text[-1:0]` is `""`. The hold-out refusal run was skipped (your decision).
- [x] 8.7 Failure analysis on dev (`docs/decisions/failure-analysis.md`), using debug traces
  re-run in 20 s from the rerank cache, with no code change. 26 of 48 dev questions fail:
  A 0, B 0, C 0, D 8, E 14, F 4, G 0. Top fix recommended, not applied: a quote-then-cite
  grounding prompt for E. Runner-up: weighted RRF for D (5 of 8 are dense-only hits sunk by
  RRF).
- `make test-int` first failed with 37 failures (output kept, not retried): every 422 path
  got a 500 because the integration rate-limit stub had no `refund()` since `639b968`; test-int
  had last run one commit before it. Deterministic, not the old 401. Stub fixed (`bdcf7f9`):
  `make lint` pass, `make test` 545 passed, `make test-int` 354 passed.
- [x] 8.6 Experiments E0-E3 and the chunk-size sweep at minimum (E4-E10 as time allows), each
  with its hypothesis written first in `docs/decisions/eval-log.md`. Include the 4.7
  hypothesis: plain RRF hurts paraphrases when the sparse list is short and the dense list
  covers the whole tenant (try weighted RRF, and `CANDIDATES` well below the corpus size).
  Done: E0-E4 plus E3-neighbors. E5-E10 not run; E5 and E9 are deferred to Later.
- [-] 8.6 Parent-child chunking (enables `EXPAND=parent`, E9): deferred to Later.
- [x] 8.7 Failure buckets A-G: classified (above). Applying and re-measuring the top fix is your
  call (needs a ~100 min dev generation run).

## Later (deferred from M8, 2026-10-11)

- [ ] Migration 3 (`eval_runs`, `eval_results`), `/v1/eval/*` endpoints, `nexus eval run`.
- [ ] `.claude/commands/run-eval.md`, `.claude/skills/eval-report/SKILL.md`, analyst subagent.
- [ ] Parent-child chunking (E9).
- [ ] Overlap sweep (E5).
- [ ] The 8.7 top fix (quote-then-cite prompt) and the runner-up (weighted RRF), each measured on
  dev. The hold-out is spent for v1; any new final check needs a dataset v2.

### Later: low findings from the M9 security review (2026-10-12)

**Needed before any public deployment:** the per-tenant API-key cap and a scheduled trace purge
(both below).
- [ ] **Scheduled trace purge.** Nothing calls `trace_repository.purge_expired`, so an idle
  tenant's questions and answers outlive `TRACE_RETENTION_DAYS`. Needs a Celery beat or cron
  job. (#8)
- [ ] **Per-tenant cap on API keys.** Key creation is admin-only but unbounded. (#6)
- [ ] **MCP: validate document ids.** `document_id` from the API goes into a path unchecked;
  validate it as a UUID first. This only matters against a malicious or compromised API. (#2)
- [ ] **API keys looked up before rate limiting.** Any `nxk_`-shaped bearer costs a DB lookup
  before rate limiting applies; consider a per-IP limit or a negative cache. (#4)
- [ ] **API keys share their creator's bucket.** A runaway MCP client can throttle its
  creator; give keys their own bucket keyed on `api_key_id`. (#5)
- [ ] **Planted request ids.** A member can plant a trace under a known request id, and an
  admin lookup returns the newest one. Return all matches, or look up by `(request_id,
  user_id)`. (#7)
- [ ] **Exception text in a log.** The pre-M9 `rate limiter unavailable (%s)` warning logs
  the exception's text. Log by type only, and add a lint or test for `%s`-with-exception. (#10)
- [ ] **A lighter lock.** `create_conversation` could lock the users row `FOR NO KEY UPDATE`
  instead of `FOR UPDATE`. (#11)

Fixed from the same review, each tests first and with lint, unit and integration green before
its commit:
- **#12, loopback ports:** postgres, redis and qdrant are published on 127.0.0.1 only
  (`f705ef2`; verified: refused on the host's network address, and the app profile is ready).
- **#1, MCP filenames:** they are framed as untrusted data like excerpts (`a342d24`).
- **#3, MCP URLs:** a malformed `NEXUS_API_URL` gives one clean line, and credentials in it are
  refused (`385b589`).
- **#9, trace docstring:** corrected; answers can quote documents (`1817df6`).

## M9: Observability, MCP server, CI/CD, hardening (closed 2026-10-12)

Your decisions (2026-10-11):
- tracing uses the standard library only, with no new dependency (OpenTelemetry vocabulary,
  no SDK);
- `query_traces` stores the query, the rewritten query and the answer, but never document
  text (chunk ids and scores only), kept 30 days;
- `GET /v1/traces/{request_id}` is admin-only, and anyone else gets 404.

Before M9: `ingest_corpus` no longer takes `--password` (`e4555f1`), and `run.json` no longer
records absolute paths (`ce64389`).
- [x] 9.1a JSON logs: one object per line (ts, level, logger, message, request_id, tenant_id,
  plus whitelisted extras such as stage and ms). The tenant is set only after a token is
  verified and reset per request. Exceptions are logged by type and file:line frames only;
  never the message or source lines (a test checks a secret in an exception never appears).
  Uvicorn and the Celery worker use the same format. Worker lines carry no tenant_id: setting
  it per task risks leaking it between tasks. Every existing log call was audited; none logs
  document text or prompts.
- [x] 9.1b `app/core/tracing.py`: one request-scoped trace per request, started by the
  request-id middleware. `with span(name):` and `record(name, ms)` add timed spans (a failing
  span records only the error's type). Wired into:
  - every retrieval stage (the existing stage timings feed it);
  - the follow-up rewrite (`rewrite`, with its mode);
  - generation (`llm_first_token`, and `generate` with model and source count).
- [x] 9.1c `query_traces` table (migration `c29cb20a16dd`, which up/down/up cleanly) and
  `trace_repository`.
  - **Ownership and deletion:** a composite FK ties the user to the tenant; a cascade from
    the conversation message means deleting a conversation deletes its traces.
  - **Contents:** stages hold ids, scores and ranks only; `est_cost` is null on the free stack.
  - **Reads and feedback:** reads are tenant-scoped (a reused request id gives the newest);
    feedback only by the trace's own user.
  - **Retention:** writing a trace purges that tenant's traces older than
    `TRACE_RETENTION_DAYS` (default 30), and `purge_expired` does every tenant.
- [x] 9.1d Every `/v1/chat` answer and every conversation turn writes one query trace,
  however the stream ends: done, error, or the client leaving (`disconnected`).
  - **What's stored:** request id, query, rewritten query, answer, error code; top-20 candidate
    ids, scores and ranks per retrieval stage plus the final items (never chunk text, which a
    test checks); latency per span; model.
  - **Tokens:** estimated (chars / 4, as the context budget counts).
  - **Conversation link:** a turn's trace points at its saved assistant message.
  - **Safety:** a failed trace write is logged by type and never breaks the answer.
- [x] 9.1e Two endpoints:
  - `POST /v1/messages/{id}/feedback` (-1 or 1, own assistant messages only, otherwise 404);
  - `GET /v1/traces/{request_id}` (admins of the tenant only; members and other tenants get
    the same 404 as a missing trace; request id validated like X-Request-ID).

  Both have a schema, example and tests (happy path, 401, 404s, 422s). ADR-0013 records the
  observability decisions.

  Known gap: the global trace purge (`purge_expired`) isn't scheduled (no cron or beat), so a
  tenant with no new answers keeps expired traces until it runs.
Your decisions (2026-10-12): add `mcp==2.3.0` (official SDK); the MCP server authenticates
with read-only, tenant-bound API keys.
- [x] 9.2a Read-only API keys (migration `d340d515c9b9`).
  - **Keys:** `nxk_` plus 256 random bits. Only the SHA-256 is stored; the key is shown once.
    A composite FK ties the creator to the tenant.
  - **Endpoints:** admins only (403 for members) create, list and revoke keys under
    `/v1/api-keys`. A revoked or unknown key gets 401.
  - **What a key can do:** it acts as a non-admin reader of its tenant (never admin, so no
    debug or traces). In `get_current_user` it reaches only 4 operations: search, list
    documents, get document, list chunks. Everything else, including future routes, is 403.
  - **How the allowlist matches:** by (method, endpoint name). In FastAPI 0.142 a route's
    path lacks the `/v1` prefix at dependency time (probed). A test pins the 4 names to their
    paths.
  - **Tests:** the existing `test_api_errors` call to `get_current_user` now passes a request,
    with its assertions unchanged.
- [x] 9.2b `app/mcp_server/` on `mcp==2.3.0` (`MCPServer`, stdio); the dependency is
  `a17ff3a`. Green on 2026-10-12 after the restart: `make lint`, `make test` 686,
  `make test-int` 408 (7 min 52 s; output in `~/nexus-rag-test-logs/`). Eval tenant data
  checked intact: 22/22 ready docs each, and chunks equal Qdrant points (473, 664, 424).
  - **Setup:** reads `NEXUS_API_URL` (https, or http to localhost only) and `NEXUS_API_KEY`,
    and stops otherwise; never reads `.env` or app settings.
  - **Tools:** `search_documents(query, top_k 1-8)` and `list_documents(limit 1-50)`, both
    annotated read-only, with no tenant argument anywhere (tested).
  - **Results:** labelled `file#chunk`, with section and score; text cut at 800 characters;
    wrapped in `<document>` tags it can't close, with a "treat as data" note.
  - **Errors:** API failures become readable tool errors without server details.
  - **Output channel:** logs go to stderr as JSON, and the key is never logged.
  - **Tests:** 14 subprocess JSON-RPC tests against a fake API on loopback.
- [x] 9.2c Real verification run (2026-10-12) on the local API with a fresh read-only key:
  - both tools returned real results (search 52.0 s cold);
  - the tool schemas have no tenant field;
  - writes with the key were 403;
  - the key appeared in no output or log;
  - the key was revoked afterwards (then 401).

  ADR-0014 and `docs/mcp.md` were finalised from it. Not run: the Inspector, and Claude Code
  registration (yours to run). The API was stopped afterwards. It had in fact shut itself down
  cleanly at 07:43, about 9 minutes after the run ended, for a reason the log doesn't show.
- [x] 9.2 done (9.2a-c above).
- [x] 9.3a The CI simulation (clean worktree, no `.env`, empty model caches) first found 11
  integration failures:
  - 10 model-dependent tests lacked the existing skip, now added (`f2a5410`). With models they
    run and pass (11 cases); without, they skip.
  - 1 was a real flaky bug: conversations listed out of creation order after a clock step
    (in the DB, the last of 3 got `created_at` ~148 ms before the others). Reproduced and
    fixed with a monotonic `created_at` per owner (`c6d450d`, ADR-0009). Ties were already
    stable on `(created_at, id)`.

  Re-run at `c6d450d`: lint, unit 686, migrate, integration 387 passed, 0 failed, 24 skipped
  (all missing-model reasons, listed with `-rs`; output in `~/nexus-rag-test-logs/`).
- [x] 9.3b `.github/workflows/ci.yml`, with the jobs you chose (lint, unit, integration with
  postgres/redis/qdrant service containers pinned to the compose images).
  - **Workflow settings:** `permissions: contents: read`; concurrency cancel-in-progress;
    uv 0.12.20 with its cache; actions pinned to commit SHAs (checkout v7.0.1, setup-uv
    v10.2.0, chosen because v10.3.0 was only 3 days old); `-rs` lists skips.
  - **Status:** UNVERIFIED on GitHub (it can't run here), but the simulation above ran the
    same steps.
  - **Deferred:** the Docker build job and eval-smoke (your choice).
  - **Pre-commit:** `.pre-commit-config.yaml` runs the project's own ruff through uv (no
    download).
- [ ] 9.3 `.github/workflows/ci.yml` (lint, unit, integration with service containers, docker
  build), `eval-smoke` workflow, pre-commit with ruff. CI can't run here, so it will be
  reported as unverified until you push.
- [x] 9.4 Container image and compose `app` profile (ADR-0015).
  - **Image:** pinned digest, uid 10001, HEALTHCHECK, 1.02 GB.
  - **Models:** the host caches, read-only.
  - **Commands:** `make app-up` and `make app-down` (stops only the app services).
  - **Verified end to end through the containers** (signup, upload, worker, search), plus:
    non-root; no secrets, models or tests in the image; read-only mounts; missing-mount
    errors; the production secret check.
  - **Found and fixed:** the dense embedder now raises `ModelNotCached` when its cache
    directory is missing.
  - **Incident:** `docker compose --profile app down` removed the infrastructure containers.
    The volumes were kept, `make up` recreated the containers, and the eval tenants are
    intact (473/664/424 chunks equal Qdrant points). `app-down` exists so it can't happen
    again.
- [ ] 9.4 (guide text) Multi-stage Dockerfile (non-root, pinned base, HEALTHCHECK, model cache as a
  volume), `.dockerignore`, compose `app` profile. Pulling a base image is a download, so I'll
  ask first.
- [x] 9.5 README rewritten from the repo: pitch, architecture, run (local and containers),
  60-second CLI demo, MCP, trace debugging, the M8 evaluation (unchanged), the ADR table,
  tenant isolation and measured limitations. Only verified facts; one TODO (fresh-clone
  `app-up`). `docs/security.md` covers the threat model, every control with `file:line` and
  its proving test (each reference checked against the repo), and the known gaps.
- [ ] 9.5 (guide text) README (only verifiable facts, TODO for anything unmeasured) and `docs/security.md`
  (controls with file:line and the proving test).
- [x] M9 security review (security-reviewer subagent on `756f623..HEAD`, focused on the MCP
  server, API keys and trace data): no critical, high or medium findings, so no fix was
  required. Low and info items, for you:
  1. `list_documents` returns filenames as plain text outside any data framing (prompt
     injection through a filename).
  2. The MCP server puts `document_id` from the API into a path without validating it as a
     UUID (only matters against a malicious server).
  3. `load_config` gives a traceback on a malformed URL, and accepts userinfo in it.
  4. Any `nxk_`-shaped bearer triggers a DB lookup before the rate limit applies.
  5. Key requests share their creator's rate-limit bucket.
  6. There is no cap on keys per tenant.
  7. A member can plant a trace under a known request id; an admin lookup gets the newest
     one.
  8. `purge_expired` is unscheduled (already a known gap).
  9. `QueryTrace`'s docstring says no document text is stored, but answers can quote it.
  10. The pre-M9 rate-limiter warning logs exception text.
  11. `create_conversation` could use `FOR NO KEY UPDATE`.
  12. Compose publishes postgres, redis and qdrant on all interfaces with the dev password.

  One reported item was checked and is wrong: overlap < chunk size IS validated
  (`config.py:120`, tested).

## M10: Advanced RAG lab (at least two builds behind flags, evaluated)

- [x] Your decision (2026-10-12): build weighted RRF and the quote-then-cite prompt, dev only.
  Contextual retrieval, multi-query/HyDE and agentic mode are not built, for reasons with
  evidence in `docs/decisions/m10-techniques.md`.
- [x] M10-1 weighted RRF behind `RRF_DENSE_WEIGHT` (default 1.0, tested unchanged;
  `8d7e01e`). The hypothesis came first (`bddaca6`), then the runs (`27609da`). E3 R@10
  34 -> 35, MRR 0.635 -> 0.639 at both 1.5 and 2.0, so it **didn't help** by the rule fixed
  beforehand; the default stays plain RRF. Runs took 7 s to 3 min (rerank cache).
- [x] M10-2 quote-then-cite prompt behind `ANSWER_STYLE` (default `cite`, tested unchanged;
  `436f555`). Hypothesis first (`161c7f1`), then one 107-min dev generation run in 3 batches
  with no alerts.
  - **Better:** cites a gold source 15/40 -> 21/41; uncited, malformed and bare-citation
    answers 0.
  - **Worse:** exact correct refusals 4/7 -> 0/7, because a Quote: line is always written,
    and Answer:-part facts 7 -> 5.
  - **Decision:** not adopted, by the rule. A refusal-first variant is a possible follow-up,
    needing your approval.
- [x] Semantic caching: design note only (no repeated-query data), in
  `docs/decisions/m10-techniques.md`.
- [x] Short notes on the M10.6 techniques (no builds), in `docs/decisions/m10-techniques.md`.
- [x] M10-3 refusal-first quote-then-cite behind `ANSWER_STYLE=quote_refusal_first`
  (default `cite`, tested unchanged; `7917b27`). Hypothesis and your decision rule first
  (`e11c316`), then one 97-min dev run in 3 batches with no alerts.
  - **Better:** exact correct refusals 5/7 (`cite` 4/7, quote 0/7); uncited and malformed 0.
  - **Worse:** 26/39 answers are a bare Quote: line; false refusals 2 (> 1); cites-gold
    18/39 (< 20).
  - **Decision:** fails 2 of 4 conditions, so `cite` stays the default (ADR-0016).
- [x] Dataset v2 stays deferred, since no default changed (your instruction).

## M11: Packaging

Your plan (2026-10-13) replaces the `docs/interview/` folder with `docs/demo.md` and
`docs/interview.md`, delivered one item at a time.

- **A load-sensitive timing test** (2026-10-13). Before the README commit, `make test`
  failed once: `test_the_near_refusal_check_is_linear_on_hostile_output` took 1.09 s against
  its absolute 1.0 s limit, with the whole machine about 2x slower (unit suite 62-69 s, about
  30 s the day before). The same suite, unchanged, then passed (730 passed); log
  `~/nexus-rag-test-logs/2026-10-13-test-m11b.out`.
  - **Fix:** all five hostile-input tests with an absolute wall-clock limit now use
    `tests/timing.assert_linear`. It times n vs 4n (4n is the old input size), best of 5,
    with batches of at least 20 ms, and fails at a ratio of 10 or more (linear is about
    4, quadratic about 16).
  - **Not weakened, measured:** each of the five fails against a deliberately quadratic
    version of its function (13.6x-16.9x), and `tests/unit/test_timing.py` keeps a
    quadratic case in the suite (17.6x vs 4.1x for a linear one).
  - **Cost:** about 20 s more unit-test time.
- [x] Item 1: README polish.
  - **Mermaid diagram,** render-checked with the mermaid-cli 11.4.2 container image (the
    npx Chromium needs `libnss3`, which WSL lacks and you didn't approve installing).
    Re-rendered until no title was clipped.
  - **Quickstart verified from a fresh clone** of `0a747da` (no `.env`, `data/`, `.venv`,
    empty HF cache):
    - steps: `make up` 4 s (images cached), `make fetch-models` 484 s (real 1.3 GB),
      `make migrate` 6 s;
    - local path: signup 201, upload ready in 7.4 s, search 27 s;
    - containers: `make app-up` 137 s; a PDF ready in 26 s, search found the right chunk.
  - **Bug found by the clone:** 0600 cache files gave "Permission denied" in the container;
    `fetch-models` now fixes the modes (`1ee06cb`, tests first).
  - **Cleanup:** the clone's three volumes deleted with your approval. The main stack's eval
    tenants are intact: 473/664/424 chunks in both Postgres and Qdrant.
  - **Content:** M10 results with raw counts and the dev-only caveat, ADR-0016, updated
    limits, and current test counts.
- [x] Item 2: `docs/demo.md`. Six steps run once in order (2026-10-13, `c51177b`): 3 min 33 s,
  no clock drift, on AC.
  - **Results:** signup 201; upload ready in 14.5 s; search 32 s; ask 150 s; B gets a 404 on
    A's document and an empty search, and its refusal takes 0.38 s; MCP initialize,
    tools/list and search_documents (10.2 s); a key DELETE gets 403, revoke 204. The key
    and password appear in no log.
  - **The answer was correct but uncited.** Kept and explained, by your choice: it's the
    measured 6/40 weakness.
  - **Not run:** the follow-up with a rewritten query (no real run is recorded; it's covered
    by integration tests) and Claude Code registration.
- [ ] Item 3: `docs/interview.md`, talking points, Q&A, and what didn't work.
- [ ] Item 4: resume bullets, measured numbers only, with dev-only claims marked.
- [ ] Item 5: final hygiene: secrets scan of the tree and history, untracked `.env` and
  `data/`, a clean tree, open Later items.
