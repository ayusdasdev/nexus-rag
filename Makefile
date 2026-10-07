.PHONY: up down dev worker test test-int lint migrate fetch-models sample-docs

up:
	docker compose up -d

down:
	docker compose down

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

sample-docs:
	uv run python scripts/make_sample_docs.py
