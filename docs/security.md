# Security

How Nexus RAG protects tenant data: the threat model, every control with where it is
implemented and the test that proves it, and the known gaps. File and line references are
as of `124a965` (2026-10-12). Design rationale lives in the ADRs (`docs/decisions/`).

## Threat model

| asset | threat | main controls |
|---|---|---|
| A tenant's documents, chunks and vectors | another tenant reads, lists, searches or deletes them (IDOR, a missing filter) | tenant only from the verified token; every query and Qdrant call scoped by tenant; composite FKs |
| A user's conversations, messages, feedback | a colleague in the same tenant reads or writes them | ownership = tenant **and** user on every conversation query |
| Answers | a malicious document steers the model (prompt injection) or exfiltrates data via links | delimiters, neutralised tags, citation validation, links reported and never fetched, no tools |
| Credentials | stolen or brute-forced tokens, passwords and keys | bcrypt, short JWTs, rate limits on auth, read-only hashed API keys |
| Logs and traces | document text, prompts or secrets leak into logs | ids and sizes only, exceptions by type, SQL parameters hidden; traces admin-only and kept 30 days |
| Cost and availability | one user exhausts LLM or upload capacity | per-tenant and per-user token buckets, answer slots, deadlines |

Out of scope here: a compromised host or database, network attackers between the API and
its own services (all local), and anything in a client that calls the API.

## Controls

### Tenant and owner isolation

| control | where | proved by |
|---|---|---|
| tenant_id comes only from the verified token; no request field can set it | `app/api/deps.py:84` (`get_current_user`), `app/api/deps.py:120` (`get_tenant_id`) | `tests/integration/test_isolation.py:188` (tenant_id in the body is rejected or has no effect) |
| Request bodies reject unknown fields (e.g. `tenant_id`) | `extra="forbid"`, e.g. `app/schemas/chat.py:25` | `tests/integration/test_chat.py` (422 incl. tenant_id), `tests/integration/test_isolation.py:188` |
| Every Qdrant search and delete carries the tenant filter | `app/repositories/vector_store.py:189` (`_filter`), used by `search_dense` (148), `search_sparse` (168), `delete_document` (136), `delete_stale` (119) | `tests/integration/test_isolation.py:266` (every vector-store search and delete is filtered), `:173` (A never gets B's chunks) |
| Qdrant and SQL are reachable only from repositories | `.importlinter` contracts (run by `make lint`) | `make lint` (3 contracts kept) |
| Chunk hydration is tenant- and ready-scoped | `app/repositories/chunk_repository.py:23` (`_searchable`) | `tests/integration/test_isolation.py:307` |
| Another tenant's document: 404 on read, chunks and delete, data intact | document repository scoping | `tests/integration/test_isolation.py:230`, `:242` |
| Conversations are owned by tenant **and** user; others get the same 404 as a missing one | `app/repositories/conversation_repository.py:69` (`_owned`) | `tests/integration/test_conversations_idor.py:91`, `:109`, `:138`, `:157` |
| The database ties owners to their tenant | composite FKs `(user_id, tenant_id) -> users`, `(conversation_id, tenant_id) -> conversations` (`app/models/conversation.py`, `app/models/trace.py`, `app/models/api_key.py`) | `tests/integration/test_conversation_repository.py` (a message filed under another tenant is rejected) |
| A rewritten follow-up never retrieves another tenant's chunks | the same tenant-scoped retrieval | `tests/integration/test_conversations_idor.py:188` |
| Pagination cursors can't be forged or replayed across scopes | HMAC-SHA256 bound to tenant/user/document/conversation, `app/core/cursors.py:36`, `:41` | `tests/unit/test_cursors.py:27` (another scope), `:35` (tampered) |

### Authentication and credentials

| control | where | proved by |
|---|---|---|
| Passwords hashed with bcrypt; at most 72 bytes (bcrypt's limit), unknown fields rejected | `app/schemas/auth.py:9` | `tests/integration/test_auth.py` |
| JWTs: 60 min; 5 s clock-skew leeway, bounded 0-60 (ADR-0006) | `app/core/security.py:63` | `tests/unit/test_security.py:24`, `:35`, `:44`, `:52` |
| Production refuses the committed dev JWT secret or a short one | `app/core/config.py:147` | `tests/unit/test_config.py:7`, `:18`; verified in the container (ADR-0015) |
| Signup and login are rate-limited per IP, per email and globally (ADR-0010) | `app/api/rate_limit.py` | `tests/integration/test_auth_rate_limit.py` |
| API keys: tenant-bound, read-only, only their SHA-256 stored, shown once, revocable (ADR-0014) | `app/core/security.py:91`, `app/repositories/api_key_repository.py` | `tests/integration/test_api_keys.py` |
| An API key reaches only 4 read operations (search, list/get document, list chunks); everything else, including future routes, is 403 | `app/api/deps.py:47` (`API_KEY_OPERATIONS`) | `tests/integration/test_api_keys.py` (8 refused routes, upload refused), `tests/unit/test_openapi.py` (the allowlist pins exactly those 4) |
| A key is never admin, even when an admin made it | `app/api/deps.py:77` | `tests/integration/test_api_keys.py` (search debug with a key is 403) |
| The CLI stores its token 0600, bound to its API URL, sent only over https or to loopback | `cli/nexus_cli.py` (ADR-0010) | `tests/unit/test_nexus_cli.py` |

### Prompt injection and output handling (ADR-0007)

| control | where | proved by |
|---|---|---|
| Retrieved text only inside `<document id='N'>` tags; forged delimiters in text, headings, questions and history are neutralised | `app/services/generation.py:75`, `:81`; rules in `app/prompts/rag_system.md` | `tests/unit/test_generation.py:256` (ignore-the-rules attack stays inside its tags), `:367` (forged delimiters) |
| The model has no tools, network or secrets | `app/providers/llm.py` (Protocol has only stream/complete) | `tests/unit/test_generation.py:281` (nothing to reveal) |
| Only citations to documents actually sent survive; ids are resolved server-side | `app/services/generation.py:147` | `tests/unit/test_generation.py:296` (fake citation dropped) |
| Links and images in answers are reported, never fetched or rendered | `app/services/generation.py:293` | `tests/unit/test_generation.py:307` |
| MCP results: excerpts wrapped in `<document>` blocks they can't close, under a "data, not instructions" note | `app/mcp_server/server.py:37` | `tests/unit/test_mcp_server.py` (document text can't close the tags) |

### The MCP server (ADR-0014)

| control | where | proved by |
|---|---|---|
| No tool takes a tenant; the key decides it on the server | `app/mcp_server/server.py` | `tests/unit/test_mcp_server.py` (no "tenant" key in any schema); real run 2026-10-12 (`docs/mcp.md`) |
| Read-only tools only (search, list) | same | real run: delete, upload and key minting with the key were 403 |
| The key travels only over https, or plain http to localhost; no redirects, no proxy env | `app/mcp_server/server.py:78` | `tests/unit/test_mcp_server.py` (unsafe config stops before serving) |
| stdout carries only the protocol; the key is never logged | `app/mcp_server/server.py` | `tests/unit/test_mcp_server.py`; real run: the key appeared in no output or API log |

### Logs, traces and errors

| control | where | proved by |
|---|---|---|
| JSON logs carry ids, sizes and timings; extras are a whitelist; no document text or prompts | `app/core/logging.py` | `tests/unit/test_logging.py`; audit of every log call (PROGRESS 9.1a) |
| Exceptions are logged by type and `file:line` frames only, never the message or source lines | `app/core/logging.py:54` | `tests/unit/test_logging.py` (a secret raised in an exception never reaches the log) |
| DB errors never carry SQL parameters into logs | `app/repositories/session.py:10` (`hide_parameters=True`) | `tests/integration/test_sql_logging.py:32`, `:40` |
| 500s are RFC 9457 problems with a request id and no stack trace | `app/api/request_id.py`, `app/api/problems.py` | `tests/unit/test_problem_details.py` |
| Query traces: no chunk text (ids, scores and ranks only); admin-only reads; others get 404 | `app/api/traces.py:73`, `app/services/query_trace.py` | `tests/integration/test_chat.py` (no document text in stages), `tests/integration/test_traces.py` |
| Traces are deleted with their conversation message and kept 30 days | `app/repositories/trace_repository.py:68` (purge on write), FK cascade | `tests/integration/test_trace_repository.py` |
| Feedback only on your own answers | `app/repositories/trace_repository.py` (`set_feedback`) | `tests/integration/test_traces.py` |

### Cost and availability

| control | where | proved by |
|---|---|---|
| Token buckets per tenant and per user (chat, search, upload, default) in Redis | `app/api/rate_limit.py:87-90` | `tests/integration/test_rate_limit.py:80`, `:94`, `:115`, `:264` |
| Spoofed forwarding headers don't move a caller to a fresh bucket | trusted-proxy handling (ADR-0010) | `tests/integration/test_rate_limit.py:134` |
| With Redis down, chat fails closed; reads fail open | `app/api/rate_limit.py` | `tests/integration/test_rate_limit.py:195` |
| At most N concurrent LLM answers; a total answer deadline | `app/services/chat.py` (ADR-0008) | `tests/integration/test_chat.py` (busy streams `llm_busy` with no LLM call) |
| Upload content type sniffed from the bytes, size capped | `app/services/file_validation.py:8`, `MAX_UPLOAD_MB` | `tests/unit/test_file_validation.py`, `tests/integration/test_documents.py` |

### Deployment (ADR-0015)

| control | where | proved by |
|---|---|---|
| The container runs as non-root (uid 10001); code and venv read-only to it | `Dockerfile` | `tests/unit/test_docker_config.py`; `id` in the containers (2026-10-12) |
| No secrets, models, uploads or tests in the image; base image pinned by digest | `Dockerfile`, `.dockerignore` | `tests/unit/test_docker_config.py`; image listing and `docker history` (2026-10-12) |
| Models mounted read-only; nothing downloaded at runtime | `docker-compose.yml` (`app` profile) | `tests/unit/test_docker_config.py`; write attempts refused, missing mounts give the make-fetch-models error (2026-10-12) |
| CI has least-privilege permissions, actions pinned to commit SHAs | `.github/workflows/ci.yml` | review only: **unverified on GitHub** |

## Known gaps and accepted risks

- **Clock steps:** the dev machine's wall clock steps backwards. Message and conversation
  order now survive it (ADR-0009). Documents, API keys and the "newest trace" for a reused
  request id still order by wall-clock `created_at` (stable and cursor-consistent, but
  possibly not creation order).
- **422s aren't metered:** a 422 refunds its rate-limit charge, so unlimited invalid
  requests aren't metered (M8 review, low). It isn't a bypass of the chat limit.
- **Tenant admins see members' traces:** questions and answers, by design (ADR-0013).
  Deleting a document doesn't delete answers that quoted it while they are within
  retention (ADR-0009, ADR-0013).
- **Expired traces of inactive tenants:** they wait for the global purge, which nothing
  schedules yet.
- **API keys don't expire:** revocation is the control (ADR-0014). A leaked key reads one
  tenant's documents until revoked.
- **Prompt injection can't be fully prevented:** the design limits the damage (one answer,
  one tenant, no tools) rather than promising prevention (ADR-0007). The MCP side can only
  mark boundaries for the calling agent.
- **The eval run files** hold the eval tenant ids. The hold-out `run.json` from before
  `ce64389` also holds an absolute local path (M8 review, low).
- **`/docs` and `/openapi.json` are public** (ADR-0010); they hold no secrets.
- **Unverified here:** the GitHub Actions workflow, the MCP Inspector and Claude Code
  registration, and a fresh-clone `docker compose --profile app up`.
