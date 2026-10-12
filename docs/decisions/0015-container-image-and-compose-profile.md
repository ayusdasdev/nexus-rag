# ADR-0015: Container image and compose `app` profile (M9)

Date: 2026-10-12
Status: accepted

## Context
M9 (guide 9.4) asks for a hardened, deployable image: multi-stage, pinned base, non-root,
a HEALTHCHECK, no secrets in layers, models in a mounted cache rather than the image, and
graceful shutdown. It also asks for compose services so the whole stack runs with one
command. The API and the Celery worker share one codebase. The models (about 1.3 GB of
fastembed cache plus the BGE tokenizer) already exist on the host, filled by
`make fetch-models`.

## Decision
- **One image, `Dockerfile`, for the API, the worker and migrations.**
  - **Base:** `python:3.12.14-slim-bookworm` pinned by digest. 3.12.15 was only 6 days old.
  - **Build stage:** `pip install uv==0.12.20`, then `uv sync --frozen --no-dev`, first
    without the project (a cached dependency layer) and then with it.
  - **Runtime stage:** only the virtualenv and the code. Both are root-owned and read-only
    to the app user, `nexus` (uid 10001).
  - **Health and shutdown:** a HEALTHCHECK on `/health`, and uvicorn with
    `--timeout-graceful-shutdown 30`.
  - **Copies:** only named paths (`app`, `cli`, `alembic`, `alembic.ini`, `pyproject.toml`,
    `uv.lock`), never the whole context. `.dockerignore` also keeps out `.env*`, `data/`,
    `eval/`, `tests/`, `.venv/` and `.git/`.
- **Models: the host's caches, mounted read-only (your choice).** `./data/fastembed_cache`
  goes to `/models/fastembed`, and the Hugging Face cache to `/models/huggingface`, both
  `:ro`. Nothing is baked in, and nothing is downloaded at runtime.
  - **Host files:** three of the hub's tree-cache files on the host were mode 0600, unreadable
    by uid 10001. The fix is a documented chmod on the host, not running as root:
    `find data/fastembed_cache -type f ! -perm -o=r -exec chmod a+r {} +`. Model files aren't
    secret.
- **Compose `app` profile**, opt-in; `make up` still starts only Postgres, Redis and Qdrant.
  - **Services:** `migrate` (alembic upgrade head, once), then `api` (port 8000) and `worker`.
  - **Configuration:** they reach the infrastructure by service name and Ollama on the host
    through `host.docker.internal`. Secrets come only from `.env` (optional, never baked);
    compose sets only addresses and paths.
  - **Uploads:** a shared `uploads` named volume, so the worker sees the API's uploads.
- **Commands:** `make app-up` and `make app-down`. `app-down` stops and removes only
  `api`, `worker` and `migrate`. `docker compose --profile app down` would also remove the
  infrastructure containers: it did on 2026-10-12, though the volumes, and so the data,
  survived.
- **Code fix found by the verification:** with the model mount missing, the dense
  embedder raised a raw `PermissionError` (fastembed creates its cache directory first)
  instead of the documented `ModelNotCached` ("run `make fetch-models`"). It now checks the
  directory first; BM25 and the reranker already did.

## Verified on 2026-10-12 (raw output in `~/nexus-rag-test-logs/`)
- **Image:** the build took 2 min 7 s (a rebuild after the fix, 49 s), with no network errors
  and the machine not rebooted. The image is **1.02 GB**.
- **App profile:** `migrate` exited 0, `/health` returned `ok`, and `/ready` reported
  Postgres, Redis and Qdrant OK.
- **Non-root:** `id` inside api and worker is uid 10001 (`nexus`).
- **Image contents:**
  - no `.env`, tests, `eval/`, fastembed models or uploads; `/app/data/uploads` is an empty
    directory that the volume mounts over;
  - the only `.onnx` files are PyMuPDF's own layout models (in the `pymupdf-layout` wheel);
  - `docker history` holds no secret-like strings.
- **Mounts:**
  - all three models load as uid 10001, and writes to both mounts fail ("Read-only file
    system");
  - without the mounts, and with no network at all, the dense embedder, BM25, the reranker
    and the tokenizer each raise the "make fetch-models" error, and nothing is created.
- **Production mode:** with the committed dev JWT secret, the API refuses to start (exit 1);
  with a strong secret it starts.
- **End to end through the containers:**
  - signup 201, then login 200;
  - an upload (202) became ready in 2.1 s, chunked by the containerised worker (its log
    shows the task succeeding; no worker ran on the host);
  - a search returned 200 in 11.6 s, with the right chunk first.
- **Make targets:** `make app-up` then `make app-down` left only the three infrastructure
  services running, with all volumes in place.

## Alternatives considered
- A named `models` volume filled by a one-off fetch container: self-contained on a new
  machine, but a second 1.3 GB copy here.
- Baking the models into the image: a 2.3 GB image, and a rebuild for every model change.
- Copying uv from the `ghcr.io/astral-sh/uv` image: one more registry to pull from;
  `pip install uv==0.12.20` pins the same version.

## Consequences
- **Fresh clones:** a new machine runs `make fetch-models` (and the chmod above, if its
  cache files are 0600) before `make app-up`.
- **Unbuilt in CI:** the image isn't built there yet; you deferred that job.
- **Ollama:** it must listen where the containers can reach it (`host.docker.internal:11434`).
  Chat through the containers wasn't exercised in this verification, only retrieval.
