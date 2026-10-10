# ADR-0004: Search returns only chunks of ready documents

Date: 2026-10-08
Status: accepted

## Context
The M4 security review found that `fetch_chunks` and `fetch_neighbors` didn't check document
status. When a document is re-processed, its old chunks and vectors stay in place while the
status moves back through `processing`, `chunked` and `embedding`. During that window, search
could return chunks that are about to be replaced, or chunks of a document that ends up
`failed`.

## Decision
- Search returns a chunk only if its document's status is `ready`. Every other status
  (`pending`, `uploaded`, `processing`, `chunked`, `embedding`, `failed`) is hidden.
- The rule lives in `chunk_repository._searchable`, which joins `documents` and filters on
  tenant and `status = ready`. Both `fetch_chunks` and `fetch_neighbors` read through it.
- `retrieve()` hydrates the whole fused list (at most 2 x `candidates` ids) before cutting it
  to `limit` or to the rerank window. A hidden chunk therefore never takes a slot.
- Qdrant isn't filtered by status. The debug trace's `dense`, `sparse` and `fused` lists still
  show what the vector search returned, hidden chunks included. That's own-tenant data, and
  debug is admin-only (ADR-0005).

## Alternatives considered
- Status in the Qdrant payload: it would have to be updated on every status change, a second
  write that can drift from Postgres. Postgres is already the source of truth for status, so it
  stays the only place the rule is checked.
- Deleting old vectors when re-processing starts: this leaves the document unsearchable for the
  whole re-processing run, and it still doesn't cover `failed` or `embedding`.

## Consequences
- Re-processing a document hides it until it is `ready` again, so there is a gap rather than
  stale answers.
- Hydration fetches up to 200 ids by primary key instead of `limit` (or 50). It's still one
  query, and the trace times it as `fetch_chunks` in both the reranked and the fused path.
- Tests: `test_chunk_repository.py` (every non-ready status, both fetches),
  `test_search.py::test_search_returns_only_chunks_of_ready_documents` (endpoint, with and
  without rerank, `limit` still filled), and
  `test_retrieval.py::test_a_chunk_the_fetcher_drops_does_not_take_a_slot_in_limit`.
