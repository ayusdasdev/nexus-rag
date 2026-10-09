# API audit (M7 7.1)

Date: 2026-10-09, HEAD `63a347f`. Done in this session, not with `claude -p` (your rule).

Sources:
- every operation from `app.openapi()`;
- the status codes raised in `app/api/*.py`;
- reading the routers.

FastAPI 0.142 nests included routers, so `app.routes` doesn't list them flat; the OpenAPI
document is the complete view.

## Every operation

`auth` = bearer security in the spec. `documented` = response codes in the spec. `raised` =
codes the code can return (from `HTTPException`s, dependencies and FastAPI itself) that the
spec doesn't list. All operations have a summary and a description.

| Method | Path | auth | documented | raised but undocumented | notes |
|---|---|---|---|---|---|
| GET | `/health` | no | 200 | - | |
| GET | `/ready` | no | 200 | 503 | |
| POST | `/auth/signup` | no | 201, 422 | 409 | duplicate of `/v1/auth/signup` |
| POST | `/auth/login` | no | 200, 422 | 401 | duplicate of `/v1/auth/login` |
| GET | `/auth/me` | yes | 200 | 401 | duplicate of `/v1/auth/me` |
| POST | `/v1/auth/signup` | no | 201, 422 | 409 | |
| POST | `/v1/auth/login` | no | 200, 422 | 401 | |
| GET | `/v1/auth/me` | yes | 200 | 401 | |
| POST | `/v1/documents` | yes | 202, 422 | 200 (dedup), 401, 413, 415, 503 | `tenant_id` from `current_user` |
| GET | `/v1/documents` | yes | 200, 422 | 401 | offset pagination; `current_user.tenant_id` |
| GET | `/v1/documents/{id}` | yes | 200, 422 | 401, 404 | `current_user.tenant_id` |
| DELETE | `/v1/documents/{id}` | yes | 204, 422 | 401, 404 | `current_user.tenant_id` |
| GET | `/v1/documents/{id}/chunks` | yes | 200, 422 | 401, 404 | offset pagination |
| POST | `/v1/search` | yes | 200, 422 | 401, 403 (debug), 500, 503 | |
| POST | `/v1/chat` | yes | 200, 401, 422, 503 | 500 | SSE |
| POST | `/v1/conversations` | yes | 201, 422 | 401, 409 | |
| GET | `/v1/conversations` | yes | 200, 422 | 401 | offset pagination |
| GET | `/v1/conversations/{id}` | yes | 200, 404, 422 | 401 | messages offset-paged |
| DELETE | `/v1/conversations/{id}` | yes | 204, 404, 422 | 401 | |
| POST | `/v1/conversations/{id}/messages` | yes | 200, 404, 422 | 401, 409, 500, 503 | SSE |

## Findings

1. **No common error shape.** Errors are FastAPI's defaults: `{"detail": "..."}` for
   `HTTPException`, `{"detail": [ ... ]}` for 422. There's no `type`, `title` or
   `request_id`. An unhandled exception gives Starlette's plain-text 500.
2. **No request id.** No `X-Request-ID` is accepted, generated, echoed or attached to logs.
3. **Offset pagination everywhere.** Documents, chunks, conversations and conversation
   messages page by `offset`. Pages drift when rows are added, and deep pages are slow.
   There's no `next_cursor`.
4. **No rate limiting.** LLM cost on `/v1/chat` and conversation messages is bounded only by
   the per-process 4-slot cap (the M5 review gap). Search (about 23 s of CPU rerank each, M5
   5.5) is unbounded.
5. **Undocumented responses.** Almost every protected route can return 401 but none lists it
   except `/v1/chat`. 404s on documents, 409/413/415/503 on upload, 403/500/503 on search, and
   409 on conversations are missing too. Once there's an error schema, every error response
   should reference it.
6. **Unversioned auth duplicates.** `/auth/*` is mounted next to `/v1/auth/*` (a deliberate
   phase-1 choice, `app/main.py`). That gives three duplicate operations in the docs with
   different operation ids. Proposal: keep both for now, but mark the unversioned ones
   `deprecated` and leave them out of the schema.
7. **Operation ids are auto-generated** (`upload_document_v1_documents_post`). They're
   unique, but they make poor client method names. Proposal: name them explicitly
   (`uploadDocument`, `listDocuments`, ...).
8. **`documents.py` reads `current_user.tenant_id`** at lines 90, 133, 155, 180 and 219,
   instead of `Depends(get_tenant_id)`, which CLAUDE.md names as the one source. Both come
   from the verified token, so this isn't a leak, but it's the one router that doesn't
   follow the rule.
9. **SSE routes have no response schema.** That's expected for a stream. The payload models
   (`SourcesEvent`, ...) are named in the description, but they aren't part of
   `components.schemas`, so clients can't generate types for them.

## Plan, in order, with risk

| # | Change | Risk | Notes |
|---|---|---|---|
| 1 | RFC 9457 problem+json handlers + `X-Request-ID` middleware (contextvar, log filter, echoed header, 500 without a stack trace) | medium: touches every error response; tests that read `detail` must keep passing | keep `detail` in the problem body, so existing clients and tests see the same field |
| 2 | Migration: composite FK `conversations(user_id, tenant_id)` -> `users(id, tenant_id)` (M6 low finding) | low-medium: new unique constraint on `users`; existing rows must satisfy the FK | tests first; the migration checks existing rows |
| 3 | Cursor pagination helper on documents, chunks, conversations and conversation messages | medium: replaces `offset` (breaking for the API, but there are no outside clients yet) | opaque, signed, tenant- and user-bound cursors; invalid -> 422 |
| 4 | Redis token-bucket limiter (tenant + user buckets; chat, search and default classes) | medium: a new dependency on Redis at request time | fail closed on LLM routes, open on others when Redis is down; fake-clock unit tests plus real-Redis integration tests |
| 5 | OpenAPI pass: documented errors with the problem schema, explicit operation ids, examples, SSE event schemas in components, unversioned auth deprecated; export `openapi.json` | low: docs only | a test checks every operation documents 401/422 as problem+json and ids are unique |
| 6 | `tenant_id` via `Depends(get_tenant_id)` in `documents.py` (finding 8) | low | behaviour unchanged; covered by the existing documents tests |
| 7 | `nexus` CLI (argparse + httpx) | low: new code, no new dependency | pure SSE parser tests; token file mode 0600 |
| 8 | Optional `Idempotency-Key` on `POST /v1/documents` | low | upload already dedups by content hash, so the value is small; done only if time allows |
