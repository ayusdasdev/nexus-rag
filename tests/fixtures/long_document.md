<!-- Snapshot of project docs, used as a realistic long input for the BGE integration test. -->
# Nexus RAG
Multi-tenant document Q&A API (RAG). Backend only.
Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Celery + Redis, Postgres, Qdrant.
## Commands
- `make up` / `make down` start/stop Postgres, Qdrant, Redis (docker compose)
- `make dev` API with reload - `make worker` Celery worker
- `make test` unit tests (fast, no network, no model downloads)
- `make test-int` integration tests (needs `make up`)
- `make lint` ruff check + ruff format --check + mypy --strict (mypy.ini) + lint-imports (.importlinter)
- `make migrate` alembic upgrade head
## Architecture rules
- Layers: api/ (thin routers) -> services/ (logic) -> repositories/ (DB + Qdrant). No SQL or
Qdrant calls outside repositories/ (enforced by `.importlinter`, run via `make lint`).
- Wherever code requires tenant_id, its value must come ONLY from the authenticated token
(Depends(get_tenant_id)). Never from a request body or query string.
- All Qdrant access goes through app/repositories/vector_store.py, which always applies the
tenant filter.
- Embeddings, reranker and LLM sit behind Protocols in app/providers/. Tests use Fake* versions.
Provider SDK imports outside app/providers/ are blocked by `.importlinter`.
- Chunk/point IDs are deterministic: uuid5(NAMESPACE, f"{document_id}:{chunk_index}").
## Conventions
- Type hints everywhere; `mypy --strict` (see mypy.ini) must pass. Pydantic v2 for every
request/response body.
- New endpoint = schema + docstring + example + tests (happy path, auth failure, validation).
- pytest; fixtures in tests/conftest.py; files named test_<module>.py.
- Conventional Commits (feat:, fix:, test:, docs:, chore:). One logical change per commit.
- Config via pydantic-settings. Secrets only in .env (gitignored).
## Do NOT
- Edit Alembic migrations that are already committed; add a new one.
- Add a dependency without first explaining why in chat, then recording it in the commit
message and in docs/decisions/dependencies.md.
- Load ML models at import time.
- Commit .env, model weights, or uploaded files.
## Definition of done
`make lint` and `make test` pass, and docs/decisions is updated (see docs/decisions/template.md)
if a design choice changed.

# Nexus RAG

Multi-tenant document Q&A API (RAG). Backend only.

## Licence

This project uses `pymupdf4llm`, which depends on PyMuPDF licensed under AGPL-3.0. Anyone who
interacts with a modified version of this service over a network must be offered its source
code. See [ADR-0001](docs/decisions/0001-pdf-parser-agpl-licence.md) for the decision and its
revisit conditions.

# ADR-0001: Use pymupdf4llm (AGPL-3.0) for PDF parsing

Date: 2026-10-04
Status: accepted

## Context
Milestone 2 ingests PDFs into heading-aware chunks. `pymupdf4llm` produces Markdown with
`#`-level headings, which the heading split depends on. It depends on PyMuPDF, which is
licensed under AGPL-3.0 or sold under a commercial licence.

## Decision
Use `pymupdf4llm` (and therefore PyMuPDF) under AGPL-3.0. No commercial licence is purchased.

## Alternatives considered
- Buy a commercial PyMuPDF licence: rejected, this is a personal portfolio project.
- A permissively licensed parser such as `pypdf`: viable, but heading detection from font size
  is weaker, so the heading split would be less reliable.

## Consequences
- AGPL-3.0 section 13 applies when the software is offered to users over a network. Anyone
  interacting with a modified version of this service must be offered its source. Because this
  project is not distributed as a commercial hosted service, this is accepted as-is.
- Revisit this decision if the project becomes a commercial hosted service or if source
  disclosure of this codebase becomes unacceptable.

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
