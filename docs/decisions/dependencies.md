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
| 2026-10-12 | mcp 2.3.0 | The official Model Context Protocol Python SDK (your approval, M9 9.2), for `app/mcp_server/`: `MCPServer` (the 2.x name of FastMCP), stdio transport, typed tool schemas and `ToolError` results. Licence MIT (checked in the installed metadata). Chosen over a hand-written JSON-RPC server, which would be our own protocol implementation to keep compatible with clients. Pulls in 14 packages: mcp-types; httpx2 and httpcore2 (a second HTTP client next to our httpx, which the server itself uses); jsonschema with attrs, referencing, rpds-py and jsonschema-specifications; sse-starlette; cryptography with cffi and pycparser (via pyjwt[crypto]); truststore. Imported only by `app/mcp_server/`. | - |

### Phase-1 stack (logged retroactively on 2026-10-08)

These came in with the skeleton (`3ef23e7`, 2026-10-01) and were never logged. Versions are the
ones pinned in `pyproject.toml`, which was restored on 2026-10-08 (it had never been committed).

| Date       | Dependency     | Why                                                                                          | Commit |
|------------|----------------|-----------------------------------------------------------------------------------------------|--------|
| 2026-10-01 | fastapi 0.142.1 | Web framework named in CLAUDE.md: async routes, Pydantic v2 validation, dependency injection (`Depends(get_tenant_id)`), generated OpenAPI. | 3ef23e7 |
| 2026-10-01 | uvicorn[standard] 0.54.0 | ASGI server for `make dev`. `[standard]` adds uvloop/httptools/watchfiles for reload and speed. | 3ef23e7 |
| 2026-10-01 | pydantic-settings 2.15.0 | Typed config from env and `.env` (CLAUDE.md: config via pydantic-settings). | 3ef23e7 |
| 2026-10-01 | sqlalchemy[asyncio] 2.1.1 | ORM and query builder named in CLAUDE.md. The async API serves the FastAPI process, and `[asyncio]` pulls greenlet. | 3ef23e7 |
| 2026-10-01 | asyncpg 0.31.0 | Async Postgres driver for SQLAlchemy in the API process. The worker uses psycopg (sync) instead. | 3ef23e7 |
| 2026-10-01 | alembic 1.20.0 | Schema migrations as versioned code (CLAUDE.md: never edit a committed migration). | 3ef23e7 |
| 2026-10-01 | redis 8.1.0 | Redis client for the `/ready` check, and later rate-limit counters (M7). Celery talks to the broker through kombu. | 3ef23e7 |
| 2026-10-01 | qdrant-client 1.19.1 | Qdrant API client, pinned to match the `qdrant/qdrant:v1.19.1` image. Imported only in `app/repositories/`. | 3ef23e7 |
| 2026-10-01 | httpx 0.28.1 (dev) | `AsyncClient` + `ASGITransport` to call the app in tests without a server. | 3ef23e7 |
| 2026-10-01 | pytest 9.1.1 (dev) | Test runner. | 3ef23e7 |
| 2026-10-01 | pytest-asyncio 1.4.0 (dev) | Async tests and the session-scoped event loop shared with the global engine. | 3ef23e7 |
| 2026-10-01 | ruff 0.16.9 (dev) | Lint and format (`make lint`, the PostToolUse hook). | 3ef23e7 |
| 2026-10-01 | mypy 2.3.1 (dev) | `mypy --strict` type checking (mypy.ini). | 3ef23e7 |
| 2026-10-08 | hatchling (build) | Build backend for the editable install of `app/`, the same backend the existing venv was built with. Build-time only. | - |
| 2026-10-09 | httpx 0.28.1 (dev -> runtime) | `OllamaProvider` and `AnthropicProvider` call their HTTP APIs with it (streaming NDJSON and SSE). Chosen over the `ollama` and `anthropic` SDKs: one HTTP client we already lock and test with, and the anthropic SDK has required `httpx2` since 1.6.0 (decision B, 2026-10-09). No new packages; `uv lock` only moved it between groups. | - |
