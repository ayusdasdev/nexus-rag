"""Tenant isolation guarantees.

Tests 1-3 exercise POST /v1/search. fake_providers (autouse) forces the endpoint's own
embedder/reranker selection to "fake" too, via the same EMBEDDER=fake switch get_reranker()
already honours - otherwise embed_query() inside the real endpoint would call the real
768-dim BGE embedder against this test's 32-dim FakeEmbedder-seeded collection.

Tests 4, 5 and 7 exercise endpoints and repositories that already exist, to confirm the
isolation they already provide. Test 6 needs neither Postgres nor Qdrant: it uses the
real in-memory Qdrant client, the way tests/unit/test_vector_store.py does.

Uses FakeEmbedder/FakeSparseEmbedder/FakeReranker throughout: no model downloads, no network.
"""

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.api.documents import get_task_queue
from app.core.config import get_settings
from app.core.ids import chunk_id
from app.main import app
from app.models.chunk import Chunk
from app.models.document import DocumentStatus
from app.providers import embeddings
from app.providers import reranker as reranker_module
from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder
from app.repositories import chunk_repository, document_repository
from app.repositories.blob_store import LocalBlobStore, get_blob_store
from app.repositories.session import session_scope
from app.repositories.vector_store import VectorPoint, VectorStore, get_vector_store

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

SEARCH_URL = "/v1/search"
QUERY_TEXT = "battery calibration procedure for Nexus Widgets"


class _Queue:
    async def enqueue_ingest(self, document_id: uuid.UUID) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: SimpleNamespace(embedder="fake")
    )
    monkeypatch.setattr(
        reranker_module, "get_settings", lambda: SimpleNamespace(embedder="fake")
    )
    embeddings.get_embedder.cache_clear()
    embeddings.get_sparse_embedder.cache_clear()
    reranker_module.get_reranker.cache_clear()
    try:
        yield
    finally:
        embeddings.get_embedder.cache_clear()
        embeddings.get_sparse_embedder.cache_clear()
        reranker_module.get_reranker.cache_clear()


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


async def _signup(client: AsyncClient) -> dict[str, Any]:
    response = await client.post(
        "/auth/signup",
        json={
            "tenant_name": f"tenant-{uuid.uuid4().hex}",
            "email": f"user-{uuid.uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _seed(
    client: AsyncClient, vector_store: VectorStore, text: str
) -> dict[str, Any]:
    """Sign up a fresh tenant, upload a doc, and give it one real, ready chunk."""
    signup = await _signup(client)
    headers = {"Authorization": f"Bearer {signup['access_token']}"}
    tenant_id = uuid.UUID(signup["user"]["tenant_id"])

    upload = await client.post(
        "/v1/documents",
        headers=headers,
        files={"file": ("notes.md", f"# Notes\n\n{text}\n".encode(), "text/markdown")},
    )
    assert upload.status_code in (200, 202), upload.text
    document_id = uuid.UUID(upload.json()["id"])

    await document_repository.set_status(document_id, DocumentStatus.ready)
    cid = chunk_id(document_id, 0)
    async with session_scope() as session:
        session.add(
            Chunk(
                id=cid,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=0,
                text=text,
                heading_path=None,
                page=None,
                token_count=len(text.split()),
            )
        )
        await session.commit()

    dense = FakeEmbedder().embed_documents([text])[0]
    sparse = FakeSparseEmbedder().embed_documents([text])[0]
    vector_store.upsert_points(
        [
            VectorPoint(
                chunk_id=cid,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=0,
                dense=dense,
                sparse_indices=sparse.indices,
                sparse_values=sparse.values,
            )
        ]
    )
    return {
        "tenant_id": tenant_id,
        "document_id": document_id,
        "chunk_id": cid,
        "headers": headers,
    }


async def _tenants(client: AsyncClient, store: VectorStore) -> dict[str, Any]:
    a = await _seed(client, store, "unrelated onboarding notes about parking passes")
    b = await _seed(client, store, QUERY_TEXT)  # a near-perfect match for the query
    return {"a": a, "b": b}


# --- 1-3: the not-yet-built search endpoint ---------------------------------------


async def test_tenant_a_search_never_returns_tenant_bs_chunks(
    client: AsyncClient, store: VectorStore, wired: None
) -> None:
    tenants = await _tenants(client, store)
    response = await client.post(
        SEARCH_URL,
        headers=tenants["a"]["headers"],
        json={"query": QUERY_TEXT, "limit": 10},
    )

    assert response.status_code == 200, response.text
    hits = response.json()["items"]
    assert all(hit["document_id"] != str(tenants["b"]["document_id"]) for hit in hits)


async def test_tenant_id_in_the_body_is_rejected_or_has_no_effect(
    client: AsyncClient, store: VectorStore, wired: None
) -> None:
    tenants = await _tenants(client, store)
    response = await client.post(
        SEARCH_URL,
        headers=tenants["a"]["headers"],
        json={
            "query": QUERY_TEXT,
            "tenant_id": str(tenants["b"]["tenant_id"]),
            "limit": 10,
        },
    )

    if response.status_code == 422:
        return
    assert response.status_code == 200, response.text
    hits = response.json()["items"]
    assert all(hit["document_id"] != str(tenants["b"]["document_id"]) for hit in hits)


async def test_document_ids_naming_another_tenants_document_returns_nothing(
    client: AsyncClient, store: VectorStore, wired: None
) -> None:
    tenants = await _tenants(client, store)
    response = await client.post(
        SEARCH_URL,
        headers=tenants["a"]["headers"],
        json={
            "query": QUERY_TEXT,
            "document_ids": [str(tenants["b"]["document_id"])],
            "limit": 10,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


# --- 4-5: existing endpoints, already expected to hold -----------------------------


async def test_get_chunks_of_another_tenants_document_is_404(
    client: AsyncClient, store: VectorStore, wired: None
) -> None:
    tenants = await _tenants(client, store)
    response = await client.get(
        f"/v1/documents/{tenants['b']['document_id']}/chunks",
        headers=tenants["a"]["headers"],
    )

    assert response.status_code == 404


async def test_delete_of_another_tenants_document_is_404_and_leaves_its_data_intact(
    client: AsyncClient, store: VectorStore, wired: None
) -> None:
    tenants = await _tenants(client, store)
    response = await client.delete(
        f"/v1/documents/{tenants['b']['document_id']}",
        headers=tenants["a"]["headers"],
    )

    assert response.status_code == 404

    get_as_b = await client.get(
        f"/v1/documents/{tenants['b']['document_id']}", headers=tenants["b"]["headers"]
    )
    assert get_as_b.status_code == 200

    dense = FakeEmbedder().embed_queries([QUERY_TEXT])[0]
    hits = store.search_dense(tenants["b"]["tenant_id"], dense, 10)
    assert any(h.document_id == tenants["b"]["document_id"] for h in hits)


# --- 6: every VectorStore search/delete carries a tenant_id filter ----------------


def test_every_vector_store_search_and_delete_is_filtered_by_tenant() -> None:
    class SpyClient(QdrantClient):
        def __init__(self) -> None:
            super().__init__(":memory:")
            self.filters: list[qm.Filter | None] = []

        def query_points(self, *args: Any, **kwargs: Any) -> Any:
            self.filters.append(kwargs.get("query_filter"))
            return super().query_points(*args, **kwargs)

        def delete(self, *args: Any, **kwargs: Any) -> Any:
            selector = kwargs.get("points_selector")
            flt = selector.filter if isinstance(selector, qm.FilterSelector) else None
            self.filters.append(flt)
            return super().delete(*args, **kwargs)

    spy = SpyClient()
    vs = VectorStore(spy, dim=FakeEmbedder.dim, collection="isolation_spy")
    vs.ensure_collection()
    tenant, document = uuid.uuid4(), uuid.uuid4()

    vs.search_dense(tenant, FakeEmbedder().embed_documents(["x"])[0], 5)
    sparse = FakeSparseEmbedder().embed_documents(["x"])[0]
    vs.search_sparse(tenant, sparse.indices, sparse.values, 5)
    vs.delete_stale(tenant, document, keep_ids=set())
    vs.delete_document(tenant, document)

    assert len(spy.filters) == 4
    for flt in spy.filters:
        assert flt is not None and flt.must is not None
        tenant_matches = [
            condition.match.value  # type: ignore[union-attr]
            for condition in flt.must
            if isinstance(condition, qm.FieldCondition) and condition.key == "tenant_id"
        ]
        assert tenant_matches == [str(tenant)]


# --- 7: the Postgres chunk fetch filters by tenant, even for a real foreign id ----


async def test_postgres_chunk_fetch_filters_by_tenant_for_a_real_foreign_document_id(
    client: AsyncClient, store: VectorStore, wired: None
) -> None:
    tenants = await _tenants(client, store)
    records, total = await chunk_repository.list_chunks(
        tenants["a"]["tenant_id"], tenants["b"]["document_id"], 10, 0
    )

    assert records == []
    assert total == 0
