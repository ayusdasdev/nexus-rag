# ADR-0003: Retrieval switches, standalone RRF and neighbor expansion

Date: 2026-10-08
Status: accepted

## Context
M8 runs single-variable experiments (dense vs sparse vs hybrid, rerank on/off, candidate
count, expansion). Each needs a switch that works both as a deployment default and per
request, without touching tenant scoping. RRF was inline in `retrieval.py`: it broke score
ties by input order and counted an id twice if it appeared twice in one list. Chunks
overlap by about 50 tokens, but an answer can still straddle a chunk boundary.

## Decision
- Settings `RETRIEVAL_MODE=dense|sparse|hybrid` (default hybrid), `RERANK` (true),
  `CANDIDATES` (40, range 1-100, results asked of each search) and `EXPAND=none|neighbors`
  (none). `POST /v1/search` accepts `mode`, `rerank`, `candidates` and `expand`. A request
  value wins, and an omitted one falls back to the setting. The request schema still
  forbids unknown fields, so `tenant_id` stays a 422.
- The default candidate count drops from 50 to 40, the guide's value. The reranker still
  scores at most `RERANK_MAX_CANDIDATES` (50).
- `app/services/fusion.py` holds pure `rrf(ranked_lists, k=60)` over list positions and
  `rrf_from_ranks` over explicit (id, rank) pairs. Both count an id at most once per list (at
  its best rank) and break ties by `str(id)`. `retrieval.fuse_rrf` delegates to
  `rrf_from_ranks`, so each candidate's own rank is used.
- `expand=neighbors` attaches the chunks at `chunk_index` -1 and +1 to each hit as
  `neighbors`, in index order. A neighbor that is itself a returned hit is left out. The
  hit's own text, score and rank are unchanged. Neighbors come from
  `chunk_repository.fetch_neighbors`, which filters by tenant and matches (document_id,
  chunk_index) as pairs.
- `expand=parent` isn't accepted yet. It depends on parent-child chunking, which is still
  reserved (`CHUNK_STRATEGY=parent_child`). It will be added with that work, rather than
  accepting a value that can only fail.

## Alternatives considered
- Neighbors returned as extra ranked items: rejected because they would carry scores they
  never earned and push real hits out of `limit`.
- Merging neighbor text into the hit's `text`: rejected. It hides what was actually
  retrieved, and with overlap the joined text repeats about 50 tokens at each seam. The
  generation step (M5) decides how to join them.
- Qdrant server-side fusion (`query_points` with prefetch): deferred. Fusing in our own code
  keeps both ranked lists visible in the debug trace, and RRF stays a tested pure function.

## Consequences
- The M8 runner can sweep mode, rerank, candidates and expand through the same settings the
  API uses.
- Neighbor expansion costs one extra tenant-scoped Postgres query per search, timed as the
  `expand` stage in the trace.
- Hits now carry `neighbors` (empty unless requested), a backwards-compatible addition to the
  response.
