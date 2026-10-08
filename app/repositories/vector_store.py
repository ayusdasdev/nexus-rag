import uuid
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http import models as qm
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.config import get_settings
from app.core.errors import TransientError
from app.providers.embeddings import get_embedder

DENSE = "dense"
SPARSE = "bm25"
BATCH_SIZE = 64
_CONFLICT = 409
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500


def collection_name(embedder_name: str) -> str:
    return "chunks__" + embedder_name.replace(".", "_")


COLLECTION = collection_name("bge-base-en-v1.5")


class VectorStoreRejected(Exception):
    """Qdrant refused the request for a reason a retry will not fix."""


@contextmanager
def _translated() -> Iterator[None]:
    try:
        yield
    except ResponseHandlingException as exc:
        raise TransientError(f"vector store unreachable: {exc}") from exc
    except UnexpectedResponse as exc:
        status = exc.status_code or 0
        if status == _TOO_MANY_REQUESTS or status >= _SERVER_ERROR:
            raise TransientError(f"vector store HTTP {status}") from exc
        raise VectorStoreRejected(f"vector store HTTP {status}") from exc


@dataclass(frozen=True)
class VectorPoint:
    chunk_id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    dense: Sequence[float]
    sparse_indices: Sequence[int]
    sparse_values: Sequence[float]


@dataclass(frozen=True)
class VectorHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    score: float


class VectorStore:
    def __init__(
        self, client: QdrantClient, *, dim: int, collection: str = COLLECTION
    ) -> None:
        self._client = client
        self._dim = dim
        self._collection = collection

    @property
    def collection(self) -> str:
        return self._collection

    def ensure_collection(self) -> None:
        with _translated():
            if not self._client.collection_exists(self._collection):
                try:
                    self._client.create_collection(
                        self._collection,
                        vectors_config={
                            DENSE: qm.VectorParams(
                                size=self._dim, distance=qm.Distance.COSINE
                            )
                        },
                        sparse_vectors_config={
                            SPARSE: qm.SparseVectorParams(modifier=qm.Modifier.IDF)
                        },
                    )
                except UnexpectedResponse as exc:
                    if exc.status_code != _CONFLICT:
                        raise
            self._client.create_payload_index(
                self._collection,
                field_name="tenant_id",
                field_schema=qm.KeywordIndexParams(
                    type=qm.KeywordIndexType.KEYWORD, is_tenant=True
                ),
            )
            self._client.create_payload_index(
                self._collection,
                field_name="document_id",
                field_schema=qm.KeywordIndexParams(type=qm.KeywordIndexType.KEYWORD),
            )

    def upsert_points(self, points: Sequence[VectorPoint]) -> None:
        with _translated():
            for start in range(0, len(points), BATCH_SIZE):
                batch = points[start : start + BATCH_SIZE]
                self._client.upsert(
                    self._collection,
                    points=[self._to_struct(point) for point in batch],
                    wait=True,
                )

    def delete_stale(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        keep_ids: Collection[uuid.UUID],
    ) -> None:
        with _translated():
            self._client.delete(
                self._collection,
                points_selector=qm.FilterSelector(
                    filter=self._filter(
                        tenant_id, document_id=document_id, exclude=keep_ids
                    )
                ),
                wait=True,
            )

    def delete_document(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> None:
        with _translated():
            if not self._client.collection_exists(self._collection):
                return
            self._client.delete(
                self._collection,
                points_selector=qm.FilterSelector(
                    filter=self._filter(tenant_id, document_id=document_id)
                ),
                wait=True,
            )

    def search_dense(
        self,
        tenant_id: uuid.UUID,
        vector: Sequence[float],
        limit: int,
        document_ids: Collection[uuid.UUID] | None = None,
    ) -> list[VectorHit]:
        if document_ids is not None and not document_ids:
            return []  # "restrict to these documents" with zero documents: match nothing
        with _translated():
            response = self._client.query_points(
                self._collection,
                query=list(vector),
                using=DENSE,
                query_filter=self._filter(tenant_id, document_ids=document_ids),
                limit=limit,
                with_payload=True,
            )
        return [self._to_hit(point) for point in response.points]

    def search_sparse(
        self,
        tenant_id: uuid.UUID,
        indices: Sequence[int],
        values: Sequence[float],
        limit: int,
        document_ids: Collection[uuid.UUID] | None = None,
    ) -> list[VectorHit]:
        if document_ids is not None and not document_ids:
            return []  # "restrict to these documents" with zero documents: match nothing
        with _translated():
            response = self._client.query_points(
                self._collection,
                query=qm.SparseVector(indices=list(indices), values=list(values)),
                using=SPARSE,
                query_filter=self._filter(tenant_id, document_ids=document_ids),
                limit=limit,
                with_payload=True,
            )
        return [self._to_hit(point) for point in response.points]

    def _filter(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID | None = None,
        document_ids: Collection[uuid.UUID] | None = None,
        exclude: Collection[uuid.UUID] = (),
    ) -> qm.Filter:
        must: list[qm.Condition] = [
            qm.FieldCondition(
                key="tenant_id", match=qm.MatchValue(value=str(tenant_id))
            )
        ]
        if document_id is not None:
            must.append(
                qm.FieldCondition(
                    key="document_id", match=qm.MatchValue(value=str(document_id))
                )
            )
        if document_ids:
            must.append(
                qm.FieldCondition(
                    key="document_id",
                    match=qm.MatchAny(any=[str(d) for d in document_ids]),
                )
            )
        must_not: list[qm.Condition] = []
        if exclude:
            must_not.append(qm.HasIdCondition(has_id=[str(i) for i in exclude]))
        return qm.Filter(must=must, must_not=must_not or None)

    @staticmethod
    def _to_struct(point: VectorPoint) -> qm.PointStruct:
        return qm.PointStruct(
            id=str(point.chunk_id),
            vector={
                DENSE: list(point.dense),
                SPARSE: qm.SparseVector(
                    indices=list(point.sparse_indices), values=list(point.sparse_values)
                ),
            },
            payload={
                "tenant_id": str(point.tenant_id),
                "document_id": str(point.document_id),
                "chunk_index": point.chunk_index,
            },
        )

    @staticmethod
    def _to_hit(point: qm.ScoredPoint) -> VectorHit:
        payload = point.payload or {}
        return VectorHit(
            chunk_id=uuid.UUID(str(point.id)),
            document_id=uuid.UUID(str(payload["document_id"])),
            chunk_index=int(payload["chunk_index"]),
            score=point.score,
        )


@lru_cache
def _client() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=get_settings().qdrant_url)


@lru_cache
def get_vector_store() -> VectorStore:
    embedder = get_embedder()
    return VectorStore(
        QdrantClient(url=get_settings().qdrant_url),
        dim=embedder.dim,
        collection=collection_name(embedder.name),
    )


async def ping() -> None:
    """Confirm the Qdrant service is reachable and responsive."""
    await _client().get_collections()
