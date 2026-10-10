import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from qdrant_client import QdrantClient

from app.api.documents import get_task_queue
from app.core.config import get_settings
from app.core.ids import chunk_id
from app.main import app
from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder
from app.repositories.blob_store import LocalBlobStore, get_blob_store
from app.repositories.vector_store import VectorPoint, VectorStore, get_vector_store

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class _Queue:
    async def enqueue_ingest(self, document_id: uuid.UUID) -> None:
        return None


@pytest.fixture
def store() -> Iterator[VectorStore]:
    client = QdrantClient(url=get_settings().qdrant_url)
    name = f"test_{uuid.uuid4().hex}"
    vs = VectorStore(client, dim=FakeEmbedder.dim, collection=name)
    vs.ensure_collection()
    app.dependency_overrides[get_vector_store] = lambda: vs
    try:
        yield vs
    finally:
        app.dependency_overrides.pop(get_vector_store, None)
        if client.collection_exists(name):
            client.delete_collection(name)
        client.close()


@pytest.fixture
def wired(tmp_path: Any) -> Iterator[None]:
    app.dependency_overrides[get_task_queue] = lambda: _Queue()
    app.dependency_overrides[get_blob_store] = lambda: LocalBlobStore(tmp_path)
    yield
    app.dependency_overrides.pop(get_task_queue, None)
    app.dependency_overrides.pop(get_blob_store, None)


async def test_search_never_returns_a_deleted_documents_points(
    client: AsyncClient, store: VectorStore, wired: None
) -> None:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "tenant_name": f"tenant-{uuid.uuid4().hex}",
            "email": f"user-{uuid.uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert signup.status_code == 201, signup.text
    token = signup.json()["access_token"]
    tenant_id = uuid.UUID(signup.json()["user"]["tenant_id"])
    headers = {"Authorization": f"Bearer {token}"}

    upload = await client.post(
        "/v1/documents",
        headers=headers,
        files={
            "file": (
                "notes.md",
                b"# Notes\n\nBattery life is eight hours.\n",
                "text/markdown",
            )
        },
    )
    assert upload.status_code in (200, 202), upload.text
    document_id = uuid.UUID(upload.json()["id"])

    text = "battery life is eight hours"
    sparse = FakeSparseEmbedder().embed_documents([text])[0]
    store.upsert_points(
        [
            VectorPoint(
                chunk_id=chunk_id(document_id, 0),
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=0,
                dense=FakeEmbedder().embed_documents([text])[0],
                sparse_indices=sparse.indices,
                sparse_values=sparse.values,
            )
        ]
    )
    dense = FakeEmbedder().embed_documents([text])[0]
    assert any(
        h.document_id == document_id for h in store.search_dense(tenant_id, dense, 10)
    )

    deleted = await client.delete(f"/v1/documents/{document_id}", headers=headers)

    assert deleted.status_code == 204
    assert not any(
        h.document_id == document_id for h in store.search_dense(tenant_id, dense, 10)
    )
    assert not any(
        h.document_id == document_id
        for h in store.search_sparse(tenant_id, sparse.indices, sparse.values, 10)
    )
