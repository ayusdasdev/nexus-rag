# ADR-0002: Embedding stage, fastembed models and delete ordering

Date: 2026-10-06
Status: accepted

## Context
Chunks must be embedded for dense (BAAI/bge-base-en-v1.5, 768-dim) and BM25 sparse search
and stored in Qdrant. Model loading must never download at runtime, re-running a task must not
duplicate or leave stale points, and deleting a document must not leave its vectors searchable.

## Decision
- Providers expose `name` and `dim`, and separate `embed_documents` and `embed_queries`.
  `EMBEDDER=bge|fake` selects the provider; `fake` has dimension 32 and gets its own
  collection (`chunks__fake-32`), so the two can never share an index. The collection name and
  vector size come from the provider, never a constant.
- BGE output is normalized to unit length explicitly, and `BGE_QUERY_INSTRUCTION` prefixes
  queries only. fastembed's `query_embed` adds no prefix for BGE, so there is no double prefix.
- Embedding runs with fastembed (ONNX). Models load from `FASTEMBED_CACHE_DIR` with
  `local_files_only=True`. A missing model raises a readable error that points to
  `make fetch-models`; nothing downloads silently. Only `make fetch-models` downloads.
- The worker chains two stages. It claims `uploaded`/`processing` for chunking, then claims
  `chunked`/`embedding` for embedding, so a retry resumes at the stage that failed.
- Within the embedding stage, points are upserted per batch (32 chunks), and only after the
  whole document is upserted is `delete_stale` run. It removes this document's points whose
  ids are not in the current chunk set. Points are keyed by deterministic chunk ids.
- `EMBED_WITH_HEADING` (default off) prepends `heading_path` to the embedded text only.
  The stored chunk text is unchanged.
- DELETE removes vector points before the row and the file. If Qdrant is unavailable the
  request returns 503 and the row survives, so the delete can be retried.
- Qdrant failures are split: connection errors, 429 and 5xx are transient and retried up to
  three times. Other 4xx responses are permanent and mark the document failed.

## Alternatives considered
- **sentence-transformers** for embeddings: loads PyTorch, a much larger install, with no
  BM25 counterpart. Rejected in favour of fastembed.
- **Delete stale before upsert:** leaves a window where the document has no vectors. Rejected.
- **Downloading models on first use:** makes the first request slow and hides network
  dependencies. Rejected for explicit fetching.
- **Deleting the row before its vectors:** a Qdrant failure would leave searchable vectors
  for a document that no longer exists. Rejected.

## Consequences
- Models are a deployment prerequisite: `make fetch-models` must run before the worker can
  embed. The error message says so.
- Changing `EMBED_WITH_HEADING` does not re-embed existing documents. Re-processing is needed.
- Points whose chunk index no longer exists are removed on re-run, so a shorter re-parse
  leaves no stale vectors.
- Retries after a transient Qdrant failure redo the batches already upserted. This is safe
  because ids are deterministic, at the cost of extra work.
