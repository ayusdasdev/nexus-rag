"""POST /v1/search must not let a backend fault surface as a bare, unhandled 500.

TransientError and VectorStoreRejected come from app/repositories/vector_store.py;
ModelNotCached comes from the embedding/reranker providers. None were caught before
this fix - app/api/documents.py's DELETE endpoint is the existing precedent for the
TransientError -> 503 mapping this mirrors.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient

from app.api.documents import get_task_queue
from app.core.errors import TransientError
from app.main import app
from app.providers.embeddings import ModelNotCached
from app.repositories.blob_store import LocalBlobStore, get_blob_store
from app.repositories.vector_store import VectorStoreRejected, get_vector_store
from app.services import retrieval

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class _Queue:
    async def enqueue_ingest(self, document_id: uuid.UUID) -> None:
        return None


class _BoomStore:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def search_dense(self, *args: Any, **kwargs: Any) -> Any:
        raise self._exc

    def search_sparse(self, *args: Any, **kwargs: Any) -> Any:
        raise self._exc


@pytest.fixture
def wired(tmp_path: Any) -> Iterator[None]:
    app.dependency_overrides[get_task_queue] = lambda: _Queue()
    app.dependency_overrides[get_blob_store] = lambda: LocalBlobStore(tmp_path)
    yield
    app.dependency_overrides.pop(get_task_queue, None)
    app.dependency_overrides.pop(get_blob_store, None)


async def _signed_up_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/v1/auth/signup",
        json={
            "tenant_name": f"tenant-{uuid.uuid4().hex}",
            "email": f"user-{uuid.uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (TransientError("qdrant unreachable"), 503),
        (VectorStoreRejected("vector store HTTP 400"), 500),
    ],
)
async def test_vector_store_faults_are_mapped_and_do_not_leak_the_raw_message(
    client: AsyncClient, wired: None, exc: Exception, expected_status: int
) -> None:
    headers = await _signed_up_headers(client)
    app.dependency_overrides[get_vector_store] = lambda: _BoomStore(exc)
    try:
        response = await client.post(
            "/v1/search", headers=headers, json={"query": "battery life"}
        )
    finally:
        app.dependency_overrides.pop(get_vector_store, None)

    assert response.status_code == expected_status, response.text
    assert str(exc) not in response.json()["detail"]


async def test_model_not_cached_is_mapped_to_503_not_a_bare_500(
    client: AsyncClient, wired: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _signed_up_headers(client)

    def _boom() -> Any:
        raise ModelNotCached("BAAI/bge-base-en-v1.5 is not in the local cache.")

    monkeypatch.setattr(retrieval, "get_embedder", _boom)

    response = await client.post(
        "/v1/search", headers=headers, json={"query": "battery life"}
    )

    assert response.status_code == 503, response.text
    assert "fetch-models" not in response.json()["detail"]
