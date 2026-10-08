# ADR-0005: Search debug trace is admin-only

Date: 2026-10-08
Status: accepted

## Context
`POST /v1/search` with `debug=true` returns the retrieval trace: per-stage timings and the
ranked chunk ids and raw scores from dense, sparse, fusion and rerank. The M4 security review
noted that any authenticated user could ask for it. The trace holds only the caller's own
tenant's data. It still exposes retrieval internals, including chunks of documents that
search hides (ADR-0004), and it makes responses larger.

## Decision
- `debug=true` requires `role = admin`. A non-admin gets 403 with
  `"debug=true is limited to admins"`. The check runs before any retrieval work.
- The role is read from the database on each request (`get_current_user`), not from the
  token's `role` claim, so a demoted user loses access immediately.
- `debug=false`, the default, is unchanged for every role.

## Alternatives considered
- Silently dropping the trace for non-admins: rejected, because a client that asked for
  debug output would get a 200 that hides why the trace is missing.
- A separate `/v1/search/debug` endpoint: rejected, as it duplicates the request schema for
  one flag.

## Consequences
- The M8 eval runner must authenticate as an admin of the eval tenant to read traces.
- Tests: `test_search.py::test_debug_search_by_a_non_admin_is_403`,
  `test_search_without_debug_by_a_non_admin_succeeds_without_a_trace`,
  `test_debug_search_by_an_admin_returns_the_trace`.
