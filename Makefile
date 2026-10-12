.PHONY: up down dev worker test test-int lint migrate fetch-models sample-docs openapi app-up app-down

up:
	docker compose up -d

down:
	docker compose down

# The containerised app (M9 9.4, ADR-0015). app-down stops only the app services:
# `docker compose --profile app down` would also remove postgres, redis and qdrant.
app-up:
	docker compose --profile app up -d --build

app-down:
	docker compose --profile app stop api worker migrate
	docker compose --profile app rm -f api worker migrate

dev:
	uv run uvicorn app.main:app --reload

worker:
	uv run celery -A app.workers.celery_app worker --loglevel=info

test:
	uv run pytest tests/unit

test-int:
	uv run pytest tests/integration

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --config-file mypy.ini
	uv run lint-imports

migrate:
	uv run alembic upgrade head

fetch-models:
	uv run python -m app.providers.tokenizer --fetch
	uv run python -m app.providers.embeddings --fetch
	uv run python -m app.providers.reranker --fetch

sample-docs:
	uv run python scripts/make_sample_docs.py

openapi:
	uv run python scripts/export_openapi.py
