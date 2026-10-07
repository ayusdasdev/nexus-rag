import uuid
from collections.abc import Iterator

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import get_settings
from app.core.ids import chunk_id
from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder
from app.repositories.vector_store import DENSE, SPARSE, VectorPoint, VectorStore

pytestmark = pytest.mark.integration


@pytest.fixture
def qdrant() -> Iterator[QdrantClient]:
    client = QdrantClient(url=get_settings().qdrant_url)
    yield client
    client.close()


@pytest.fixture
def store(qdrant: QdrantClient) -> Iterator[VectorStore]:
    name = f"test_{uuid.uuid4().hex}"
    vs = VectorStore(qdrant, dim=FakeEmbedder.dim, collection=name)
    vs.ensure_collection()
    try:
        yield vs
    finally:
        qdrant.delete_collection(name)


def _point(
    tenant: uuid.UUID, document: uuid.UUID, index: int, text: str
) -> VectorPoint:
    sparse = FakeSparseEmbedder().embed_documents([text])[0]
    return VectorPoint(
        chunk_id=chunk_id(document, index),
        tenant_id=tenant,
        document_id=document,
        chunk_index=index,
        dense=FakeEmbedder().embed_documents([text])[0],
        sparse_indices=sparse.indices,
        sparse_values=sparse.values,
    )


def test_collection_has_named_vectors_idf_and_tenant_index(
    store: VectorStore, qdrant: QdrantClient
) -> None:
    info = qdrant.get_collection(store.collection)

    dense = info.config.params.vectors[DENSE]  # type: ignore[index]
    assert isinstance(dense, qm.VectorParams)
    assert dense.size == FakeEmbedder.dim
    assert dense.distance == qm.Distance.COSINE

    sparse = info.config.params.sparse_vectors[SPARSE]  # type: ignore[index]
    assert sparse.modifier == qm.Modifier.IDF

    tenant_index = info.payload_schema["tenant_id"]
    assert tenant_index.data_type == qm.PayloadSchemaType.KEYWORD
    assert tenant_index.params.is_tenant is True  # type: ignore[union-attr]
    assert "document_id" in info.payload_schema


def test_ensure_collection_is_idempotent(store: VectorStore) -> None:
    store.ensure_collection()
    store.ensure_collection()


def test_upsert_then_search_both_vectors(store: VectorStore) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    store.upsert_points([_point(tenant, document, 0, "battery powered sensors")])
    sparse = FakeSparseEmbedder().embed_documents(["battery powered sensors"])[0]

    dense_hits = store.search_dense(
        tenant, FakeEmbedder().embed_documents(["battery powered sensors"])[0], 3
    )
    sparse_hits = store.search_sparse(tenant, sparse.indices, sparse.values, 3)

    assert dense_hits[0].chunk_id == chunk_id(document, 0)
    assert sparse_hits[0].chunk_id == chunk_id(document, 0)


def test_cross_tenant_search_never_returns_another_tenants_points(
    store: VectorStore,
) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    store.upsert_points(
        [
            _point(tenant_a, doc_a, 0, "shared words here"),
            _point(tenant_b, doc_b, 0, "shared words here"),
        ]
    )
    dense = FakeEmbedder().embed_documents(["shared words here"])[0]
    sparse = FakeSparseEmbedder().embed_documents(["shared words here"])[0]

    for hits in (
        store.search_dense(tenant_a, dense, 10),
        store.search_sparse(tenant_a, sparse.indices, sparse.values, 10),
    ):
        assert [hit.document_id for hit in hits] == [doc_a]


def test_delete_stale_removes_only_points_outside_the_keep_set(
    store: VectorStore, qdrant: QdrantClient
) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    store.upsert_points([_point(tenant, document, i, f"chunk {i}") for i in range(5)])
    keep = {chunk_id(document, 0), chunk_id(document, 1)}

    store.delete_stale(tenant, document, keep_ids=keep)

    remaining = store.search_dense(
        tenant, FakeEmbedder().embed_documents(["chunk"])[0], 10
    )
    assert {hit.chunk_id for hit in remaining} == keep


def test_delete_stale_never_removes_another_tenants_points(store: VectorStore) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    document = uuid.uuid4()
    store.upsert_points([_point(tenant_b, document, 0, "alpha")])

    store.delete_stale(tenant_a, document, keep_ids=set())

    assert (
        len(
            store.search_dense(
                tenant_b, FakeEmbedder().embed_documents(["alpha"])[0], 10
            )
        )
        == 1
    )


def test_large_upsert_is_stored_in_full(
    store: VectorStore, qdrant: QdrantClient
) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    count = 150
    store.upsert_points(
        [_point(tenant, document, i, f"chunk {i}") for i in range(count)]
    )

    assert qdrant.count(store.collection, exact=True).count == count
