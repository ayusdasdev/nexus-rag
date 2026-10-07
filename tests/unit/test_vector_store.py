import uuid
from typing import Any

import pytest
from httpx import Headers
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.errors import TransientError
from app.core.ids import chunk_id
from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder
from app.repositories.vector_store import (
    BATCH_SIZE,
    COLLECTION,
    VectorPoint,
    VectorStore,
    VectorStoreRejected,
    collection_name,
)


class SpyClient(QdrantClient):
    """Real in-memory Qdrant that records the filter of every read and delete."""

    def __init__(self) -> None:
        super().__init__(":memory:")
        self.read_filters: list[qm.Filter | None] = []
        self.delete_filters: list[qm.Filter | None] = []
        self.upsert_sizes: list[int] = []

    def query_points(self, *args: Any, **kwargs: Any) -> Any:
        self.read_filters.append(kwargs.get("query_filter"))
        return super().query_points(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        selector = kwargs.get("points_selector")
        self.delete_filters.append(
            selector.filter if isinstance(selector, qm.FilterSelector) else None
        )
        return super().delete(*args, **kwargs)

    def upsert(self, *args: Any, **kwargs: Any) -> Any:
        self.upsert_sizes.append(len(kwargs["points"]))
        return super().upsert(*args, **kwargs)


def _tenant_conditions(flt: qm.Filter | None) -> list[str]:
    if flt is None or not flt.must:
        return []
    return [
        str(condition.match.value)  # type: ignore[union-attr]
        for condition in flt.must
        if isinstance(condition, qm.FieldCondition) and condition.key == "tenant_id"
    ]


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


@pytest.fixture
def spy() -> SpyClient:
    return SpyClient()


@pytest.fixture
def store(spy: SpyClient) -> VectorStore:
    vs = VectorStore(spy, dim=FakeEmbedder.dim)
    vs.ensure_collection()
    return vs


def test_collection_name_matches_the_model() -> None:
    assert COLLECTION == "chunks__bge-base-en-v1_5"


def test_ensure_collection_is_safe_to_call_repeatedly(store: VectorStore) -> None:
    store.ensure_collection()
    store.ensure_collection()


def test_upsert_is_batched(store: VectorStore, spy: SpyClient) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    points = [
        _point(tenant, document, i, f"chunk {i}") for i in range(BATCH_SIZE * 2 + 5)
    ]

    store.upsert_points(points)

    assert spy.upsert_sizes == [BATCH_SIZE, BATCH_SIZE, 5]


def test_search_dense_returns_the_matching_chunk(store: VectorStore) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    store.upsert_points([_point(tenant, document, 0, "battery powered sensors")])

    hits = store.search_dense(
        tenant, FakeEmbedder().embed_documents(["battery powered sensors"])[0], limit=3
    )

    assert hits[0].chunk_id == chunk_id(document, 0)
    assert hits[0].document_id == document


def test_search_sparse_returns_the_matching_chunk(store: VectorStore) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    store.upsert_points([_point(tenant, document, 0, "battery powered sensors")])
    query = FakeSparseEmbedder().embed_documents(["battery powered sensors"])[0]

    hits = store.search_sparse(tenant, query.indices, query.values, limit=3)

    assert hits[0].chunk_id == chunk_id(document, 0)


def test_every_read_is_filtered_by_tenant(store: VectorStore, spy: SpyClient) -> None:
    tenant = uuid.uuid4()
    store.search_dense(tenant, FakeEmbedder().embed_documents(["q"])[0], limit=1)
    query = FakeSparseEmbedder().embed_documents(["q"])[0]
    store.search_sparse(tenant, query.indices, query.values, limit=1)

    assert len(spy.read_filters) == 2
    for flt in spy.read_filters:
        assert _tenant_conditions(flt) == [str(tenant)]


def test_every_delete_is_filtered_by_tenant(store: VectorStore, spy: SpyClient) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    store.delete_stale(tenant, document, keep_ids=set())

    assert spy.delete_filters
    for flt in spy.delete_filters:
        assert _tenant_conditions(flt) == [str(tenant)]


def test_search_requires_a_tenant_id(store: VectorStore) -> None:
    with pytest.raises(TypeError):
        store.search_dense(vector=FakeEmbedder().embed_documents(["q"])[0], limit=1)  # type: ignore[call-arg]


def test_delete_stale_keeps_current_chunks_and_removes_the_rest(
    store: VectorStore,
) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    store.upsert_points([_point(tenant, document, i, f"chunk {i}") for i in range(4)])
    keep = {chunk_id(document, 0), chunk_id(document, 1)}

    store.delete_stale(tenant, document, keep_ids=keep)

    remaining = {
        hit.chunk_id
        for hit in store.search_dense(
            tenant, FakeEmbedder().embed_documents(["chunk"])[0], limit=10
        )
    }
    assert remaining == keep


def test_delete_stale_with_no_keep_ids_removes_the_whole_document(
    store: VectorStore,
) -> None:
    tenant, document = uuid.uuid4(), uuid.uuid4()
    store.upsert_points([_point(tenant, document, i, f"chunk {i}") for i in range(3)])

    store.delete_stale(tenant, document, keep_ids=set())

    assert (
        store.search_dense(
            tenant, FakeEmbedder().embed_documents(["chunk"])[0], limit=10
        )
        == []
    )


def test_delete_stale_leaves_other_documents_of_the_same_tenant(
    store: VectorStore,
) -> None:
    tenant = uuid.uuid4()
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    store.upsert_points(
        [_point(tenant, doc_a, 0, "alpha"), _point(tenant, doc_b, 0, "alpha")]
    )

    store.delete_stale(tenant, doc_a, keep_ids=set())

    hits = store.search_dense(
        tenant, FakeEmbedder().embed_documents(["alpha"])[0], limit=10
    )
    assert [hit.document_id for hit in hits] == [doc_b]


def test_delete_stale_never_touches_another_tenant(store: VectorStore) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    document = uuid.uuid4()
    store.upsert_points([_point(tenant_b, document, 0, "alpha")])

    store.delete_stale(tenant_a, document, keep_ids=set())

    hits = store.search_dense(
        tenant_b, FakeEmbedder().embed_documents(["alpha"])[0], limit=10
    )
    assert len(hits) == 1


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

    dense_hits = store.search_dense(tenant_a, dense, limit=10)
    sparse_hits = store.search_sparse(tenant_a, sparse.indices, sparse.values, limit=10)

    assert [hit.document_id for hit in dense_hits] == [doc_a]
    assert [hit.document_id for hit in sparse_hits] == [doc_a]


def test_connection_failure_maps_to_transient_error(
    store: VectorStore, spy: SpyClient
) -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise ResponseHandlingException(ConnectionError("connection refused"))

    spy.upsert = refused  # type: ignore[method-assign]

    with pytest.raises(TransientError):
        store.upsert_points([_point(uuid.uuid4(), uuid.uuid4(), 0, "x")])


@pytest.mark.parametrize(
    ("status", "expected"),
    [(503, TransientError), (429, TransientError), (400, VectorStoreRejected)],
)
def test_http_errors_are_split_into_transient_and_permanent(
    store: VectorStore, spy: SpyClient, status: int, expected: type[Exception]
) -> None:
    def respond(*args: Any, **kwargs: Any) -> None:
        raise UnexpectedResponse(status, "reason", b"body", Headers())

    spy.upsert = respond  # type: ignore[method-assign]

    with pytest.raises(expected):
        store.upsert_points([_point(uuid.uuid4(), uuid.uuid4(), 0, "x")])


def test_delete_document_on_missing_collection_is_a_no_op() -> None:
    store = VectorStore(SpyClient(), dim=FakeEmbedder.dim, collection="never_created")

    store.delete_document(uuid.uuid4(), uuid.uuid4())


def test_delete_document_removes_only_that_document_of_that_tenant(
    store: VectorStore,
) -> None:
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    doc, other_doc = uuid.uuid4(), uuid.uuid4()
    store.upsert_points(
        [
            _point(tenant, doc, 0, "alpha"),
            _point(tenant, other_doc, 0, "alpha"),
            _point(other_tenant, doc, 0, "alpha"),
        ]
    )

    store.delete_document(tenant, doc)

    dense = FakeEmbedder().embed_documents(["alpha"])[0]
    assert [h.document_id for h in store.search_dense(tenant, dense, 10)] == [other_doc]
    assert len(store.search_dense(other_tenant, dense, 10)) == 1


def test_collection_name_is_derived_from_the_embedder_name() -> None:
    assert collection_name("bge-base-en-v1.5") == "chunks__bge-base-en-v1_5"
    assert collection_name("fake-32") == "chunks__fake-32"
