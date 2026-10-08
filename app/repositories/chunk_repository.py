from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, func, select, tuple_

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.repositories.session import session_scope


@dataclass(frozen=True)
class ChunkRecord:
    id: UUID
    document_id: UUID
    chunk_index: int
    text: str
    heading_path: str | None
    page: int | None
    token_count: int


def _searchable(tenant_id: UUID) -> Select[Chunk]:
    """Chunks of the tenant whose document is ready. Search reads only through this: a
    document being re-processed, still embedding, or failed contributes nothing."""
    return (
        select(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
            Document.status == DocumentStatus.ready,
        )
    )


def _to_record(row: Chunk) -> ChunkRecord:
    return ChunkRecord(
        id=row.id,
        document_id=row.document_id,
        chunk_index=row.chunk_index,
        text=row.text,
        heading_path=row.heading_path,
        page=row.page,
        token_count=row.token_count,
    )


async def fetch_chunks(tenant_id: UUID, ids: Sequence[UUID]) -> list[ChunkRecord]:
    """Chunks by id, scoped to the tenant and to ready documents. An id from another
    tenant, or from a document that isn't ready, is silently dropped."""
    if not ids:
        return []
    async with session_scope() as session:
        result = await session.execute(_searchable(tenant_id).where(Chunk.id.in_(ids)))
        return [_to_record(row) for row in result.scalars().all()]


async def fetch_neighbors(
    tenant_id: UUID, keys: Sequence[tuple[UUID, int]]
) -> list[ChunkRecord]:
    """Chunks by (document_id, chunk_index), scoped to the tenant and to ready documents.

    Matched as pairs, so asking for (doc_1, 0) never returns (doc_2, 0). A key whose
    document belongs to another tenant, or isn't ready, is silently dropped.
    """
    if not keys:
        return []
    async with session_scope() as session:
        result = await session.execute(
            _searchable(tenant_id).where(
                tuple_(Chunk.document_id, Chunk.chunk_index).in_(keys)
            )
        )
        return [_to_record(row) for row in result.scalars().all()]


async def list_chunks(
    tenant_id: UUID, document_id: UUID, limit: int, offset: int
) -> tuple[list[ChunkRecord], int]:
    async with session_scope() as session:
        scope = (Chunk.tenant_id == tenant_id, Chunk.document_id == document_id)
        total = await session.scalar(
            select(func.count()).select_from(Chunk).where(*scope)
        )
        result = await session.execute(
            select(Chunk)
            .where(*scope)
            .order_by(Chunk.chunk_index)
            .limit(limit)
            .offset(offset)
        )
        records = [_to_record(row) for row in result.scalars().all()]
        return records, int(total or 0)
