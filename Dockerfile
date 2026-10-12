# syntax=docker/dockerfile:1
# Nexus RAG API and worker image (M9 9.4, ADR-0015). Multi-stage: dependencies are built in
# `build`, and `runtime` gets only the virtualenv and the code. No secrets, models or uploads
# in any layer: config comes from the environment, and models and uploads are mounted.

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never
RUN pip install uv==0.12.20
WORKDIR /app
# Dependencies first, so code changes don't rebuild them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY cli ./cli
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin nexus \
    && mkdir -p /app/data/uploads \
    && chown nexus:nexus /app/data/uploads
WORKDIR /app
# Code and virtualenv stay root-owned and read-only to the app user.
COPY --from=build /app /app
USER nexus
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
# SIGTERM stops accepting connections; in-flight requests get 30 s to finish.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]
