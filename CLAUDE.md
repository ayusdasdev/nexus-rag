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
- Prompts live in app/prompts/*.md and are loaded at runtime via app/services/prompts.load_prompt;
never inline a prompt in code. Retrieved text goes only inside <document> tags (ADR-0007).
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
