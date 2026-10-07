# Dependency log

Every new dependency must be explained in chat *before* it's added, then logged here in the
same commit that adds it (see CLAUDE.md "Do NOT").

| Date       | Dependency     | Why                                                                                          | Commit |
|------------|----------------|-----------------------------------------------------------------------------------------------|--------|
| 2026-09-30 | import-linter  | Enforces the "DB/Qdrant calls only in repositories/" and "provider SDKs only in providers/" architecture rules automatically (`.importlinter`), instead of relying on code review to catch violations. | - |
| 2026-10-02 | PyJWT          | JWT encode/decode for the auth token scheme (claims sub/tid/role/exp, HS256). Chosen over python-jose: smaller surface, ships py.typed (mypy --strict compatible), FastAPI-ecosystem default. | - |
| 2026-10-02 | bcrypt         | Password hashing. Chosen over passlib (unmaintained, no real type stubs) and argon2-cffi (needs libffi/cffi at build time); bcrypt ships prebuilt wheels and py.typed. | - |
| 2026-10-04 | pymupdf4llm 1.28.2 | PDF to Markdown with `#`-level headings, which the heading-based chunk split depends on. Licence AGPL-3.0 (via PyMuPDF), accepted in ADR-0001. Transitively pulls `pymupdf` 1.28.2, `pymupdf-layout`, and `onnxruntime` (heavier than expected). | - |
| 2026-10-04 | psycopg[binary] 3.3.6 | Sync Postgres driver for Celery workers. Avoids reusing the async engine across per-task event loops, which breaks pooled connections. | - |
| 2026-10-04 | tokenizers 0.23.2 | Loads the BAAI/bge-base-en-v1.5 tokenizer for token counting. Chosen over `transformers` (much larger, pulls PyTorch). Only imported from `app/providers/`. | - |
| 2026-10-04 | python-multipart 0.0.32 | Required by FastAPI to parse `multipart/form-data` for `POST /v1/documents` (`UploadFile`/`File`). No framework-native alternative. | - |
| 2026-10-04 | celery 5.6.3 | Task queue. The API enqueues `ingest_document`, and the worker consumes it. Direct dependency of the app (`app/workers`). Uses the Redis broker. | - |
| 2026-10-04 | pymupdf-layout 1.28.2 | Transitive, required by pymupdf4llm 1.28.2. Layout analysis that pymupdf4llm uses for its Markdown output (headings, tables). Not imported directly. | - |
| 2026-10-04 | onnxruntime 1.30.0 | Transitive, required by pymupdf-layout. Runs its ONNX layout model on CPU. Largest transitive package here; it is the main reason the install is heavy. | - |
| 2026-10-05 | trafilatura 2.3.0 | HTML main-content extraction (drops nav/footer/boilerplate, keeps headings and lists as Markdown). Licence Apache-2.0 (checked in the installed LICENSE). Chosen over readability-lxml (less maintained) and hand-written BeautifulSoup stripping. Only imported from `app/providers/`. | - |
| 2026-10-06 | fastembed 0.8.1 | ONNX-based embeddings for both the dense BGE model (BAAI/bge-base-en-v1.5, dim 768) and the BM25 sparse model (Qdrant/bm25), in one library. Chosen over sentence-transformers to avoid a PyTorch dependency; onnxruntime is already installed transitively via pymupdf-layout. Pulls in loguru, mmh3, pillow, py-rust-stemmers, requests. | - |
