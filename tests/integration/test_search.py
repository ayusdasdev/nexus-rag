"""POST /v1/search: retrieval switches (mode, rerank, candidates, expand) and their
defaults from settings.

One tenant, one document with three chunks (0, 1, 2), seeded straight into Postgres and
a per-test Qdrant collection with the fake embedders. No model downloads, no network.
"""

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from qdrant_client import QdrantClient

from app.api.documents import get_task_queue
from app.core.config import Settings, get_settings
from app.core.ids import chunk_id
from app.main import app
from app.models.chunk import Chunk
from app.models.document import DocumentStatus
from app.providers import embeddings
from app.providers import reranker as reranker_module
from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder
from app.repositories import document_repository
from app.repositories.blob_store import LocalBlobStore, get_blob_store
from app.repositories.session import session_scope
from app.repositories.vector_store import VectorPoint, VectorStore, get_vector_store

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

SEARCH_URL = "/v1/search"
TEXTS = [
    "Charging the widget takes two hours from empty.",
    "Battery calibration: drain fully, then charge without interruption.",
    "Warranty claims need the original receipt.",
]
QUERY = "battery calibration"


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
def store(tmp_path: Any) -> Iterator[VectorStore]:
    client = QdrantClient(url=get_settings().qdrant_url)
    name = f"test_{uuid.uuid4().hex}"
    vs = VectorStore(client, dim=FakeEmbedder.dim, collection=name)
    vs.ensure_collection()
    app.dependency_overrides[get_vector_store] = lambda: vs
    app.dependency_overrides[get_task_queue] = lambda: _Queue()
    app.dependency_overrides[get_blob_store] = lambda: LocalBlobStore(tmp_path)
    try:
        yield vs
    finally:
        for dependency in (get_vector_store, get_task_queue, get_blob_store):
            app.dependency_overrides.pop(dependency, None)
        if client.collection_exists(name):
            client.delete_collection(name)
        client.close()


async def _seeded(client: AsyncClient, store: VectorStore) -> dict[str, Any]:
    signup = await client.post(
        "/auth/signup",
        json={
            "tenant_name": f"tenant-{uuid.uuid4().hex}",
            "email": f"user-{uuid.uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert signup.status_code == 201, signup.text
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    tenant_id = uuid.UUID(signup.json()["user"]["tenant_id"])
    ids = await _add_document(client, store, headers, tenant_id, TEXTS)
    return {"headers": headers, "tenant_id": tenant_id, "chunk_ids": ids}


async def _add_document(
    client: AsyncClient,
    store: VectorStore,
    headers: dict[str, str],
    tenant_id: uuid.UUID,
    texts: list[str],
    status: DocumentStatus = DocumentStatus.ready,
) -> list[uuid.UUID]:
    """Upload a document, then seed its chunks and vectors directly, in `status`."""
    upload = await client.post(
        "/v1/documents",
        headers=headers,
        files={"file": ("widget.md", "\n\n".join(texts).encode(), "text/markdown")},
    )
    assert upload.status_code in (200, 202), upload.text
    document_id = uuid.UUID(upload.json()["id"])
    await document_repository.set_status(document_id, status)

    ids = [chunk_id(document_id, index) for index in range(len(texts))]
    async with session_scope() as session:
        for index, text in enumerate(texts):
            session.add(
                Chunk(
                    id=ids[index],
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=index,
                    text=text,
                    heading_path=None,
                    page=None,
                    token_count=len(text.split()),
                )
            )
        await session.commit()

    dense = FakeEmbedder().embed_documents(texts)
    sparse = FakeSparseEmbedder().embed_documents(texts)
    store.upsert_points(
        [
            VectorPoint(
                chunk_id=ids[index],
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=index,
                dense=dense[index],
                sparse_indices=sparse[index].indices,
                sparse_values=sparse[index].values,
            )
            for index in range(len(texts))
        ]
    )
    return ids


async def _search(
    client: AsyncClient, headers: dict[str, str], **body: Any
) -> dict[str, Any]:
    response = await client.post(
        SEARCH_URL, headers=headers, json={"query": QUERY, "debug": True, **body}
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _stage_names(result: dict[str, Any]) -> set[str]:
    return {stage["name"] for stage in result["trace"]["stages"]}


async def test_search_without_a_token_is_401(client: AsyncClient) -> None:
    response = await client.post(SEARCH_URL, json={"query": QUERY})

    assert response.status_code == 401


async def test_search_with_an_unknown_mode_is_422(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)

    response = await client.post(
        SEARCH_URL,
        headers=seeded["headers"],
        json={"query": QUERY, "mode": "keyword"},
    )

    assert response.status_code == 422


async def test_default_search_is_hybrid_and_reranked(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)

    result = await _search(client, seeded["headers"])

    assert {"dense_search", "sparse_search", "fuse", "rerank"} <= _stage_names(result)
    assert result["items"]
    assert all(hit["neighbors"] == [] for hit in result["items"])


async def test_dense_mode_skips_the_sparse_search(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)

    result = await _search(client, seeded["headers"], mode="dense")

    assert "sparse_search" not in _stage_names(result)
    assert result["trace"]["sparse"] == []
    assert result["trace"]["dense"]


async def test_sparse_mode_skips_the_dense_search(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)

    result = await _search(client, seeded["headers"], mode="sparse")

    assert "dense_search" not in _stage_names(result)
    assert result["trace"]["dense"] == []
    assert result["trace"]["sparse"]


async def test_rerank_false_returns_fused_order_without_a_rerank_stage(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)

    result = await _search(client, seeded["headers"], rerank=False)

    assert "rerank" not in _stage_names(result)
    fused_ids = [item["chunk_id"] for item in result["trace"]["fused"]]
    assert [hit["chunk_id"] for hit in result["items"]] == fused_ids[
        : len(result["items"])
    ]


async def test_candidates_caps_each_search_list(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)

    result = await _search(client, seeded["headers"], candidates=1)

    assert len(result["trace"]["dense"]) == 1
    assert len(result["trace"]["sparse"]) <= 1


async def test_expand_neighbors_attaches_adjacent_chunks(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)

    result = await _search(client, seeded["headers"], expand="neighbors", limit=1)

    # Whichever chunk ranks first, its neighbors are the chunks either side of it.
    hit = result["items"][0]
    hit_index = [str(c) for c in seeded["chunk_ids"]].index(hit["chunk_id"])
    expected = [i for i in (hit_index - 1, hit_index + 1) if 0 <= i < len(TEXTS)]
    assert [n["chunk_index"] for n in hit["neighbors"]] == expected
    assert [n["text"] for n in hit["neighbors"]] == [TEXTS[i] for i in expected]
    assert "expand" in _stage_names(result)


async def test_settings_supply_the_defaults_when_the_request_omits_a_switch(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)
    app.dependency_overrides[get_settings] = lambda: Settings(
        retrieval_mode="sparse", rerank=False, expand="neighbors"
    )
    try:
        result = await _search(client, seeded["headers"])
    finally:
        app.dependency_overrides.pop(get_settings, None)

    names = _stage_names(result)
    assert "dense_search" not in names
    assert "rerank" not in names
    assert "expand" in names


async def test_a_request_switch_overrides_the_setting(
    client: AsyncClient, store: VectorStore
) -> None:
    seeded = await _seeded(client, store)
    app.dependency_overrides[get_settings] = lambda: Settings(retrieval_mode="sparse")
    try:
        result = await _search(client, seeded["headers"], mode="dense")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert "dense_search" in _stage_names(result)
    assert "sparse_search" not in _stage_names(result)


@pytest.mark.parametrize(
    "switches",
    [
        {"mode": "dense", "rerank": False},
        {"mode": "sparse", "rerank": False},
        {"mode": "hybrid", "rerank": False},
        {"mode": "hybrid", "rerank": True},
        {"mode": "hybrid", "rerank": True, "expand": "neighbors"},
    ],
)
async def test_no_switch_combination_returns_another_tenants_chunks(
    client: AsyncClient, store: VectorStore, switches: dict[str, Any]
) -> None:
    # Both tenants hold identical texts in the same collection, so any missing
    # tenant filter would surface A's chunks for B.
    tenant_a = await _seeded(client, store)
    tenant_b = await _seeded(client, store)

    result = await _search(client, tenant_b["headers"], **switches)

    own = {str(c) for c in tenant_b["chunk_ids"]}
    returned = {item["chunk_id"] for item in result["items"]}
    returned |= {n["chunk_id"] for item in result["items"] for n in item["neighbors"]}
    for stage in ("dense", "sparse", "fused", "rerank"):
        returned |= {entry["chunk_id"] for entry in result["trace"].get(stage) or []}
    assert result["items"]
    assert returned <= own
    assert not returned & {str(c) for c in tenant_a["chunk_ids"]}


NOT_READY = [status for status in DocumentStatus if status is not DocumentStatus.ready]


@pytest.mark.parametrize("rerank", [False, True], ids=["fused", "reranked"])
@pytest.mark.parametrize("status", NOT_READY, ids=[s.value for s in NOT_READY])
async def test_search_returns_only_chunks_of_ready_documents(
    client: AsyncClient, store: VectorStore, status: DocumentStatus, rerank: bool
) -> None:
    seeded = await _seeded(client, store)
    # Same tenant, text equal to the query, so it would rank first if it leaked.
    hidden = await _add_document(
        client, store, seeded["headers"], seeded["tenant_id"], [QUERY], status
    )

    result = await _search(
        client,
        seeded["headers"],
        limit=len(TEXTS),
        rerank=rerank,
        expand="neighbors",
    )

    returned = {item["chunk_id"] for item in result["items"]}
    returned |= {n["chunk_id"] for item in result["items"] for n in item["neighbors"]}
    assert str(hidden[0]) not in returned
    # The hidden chunk must not take a slot: limit is filled from the ready document.
    assert len(result["items"]) == len(TEXTS)
    assert {item["chunk_id"] for item in result["items"]} <= {
        str(c) for c in seeded["chunk_ids"]
    }
