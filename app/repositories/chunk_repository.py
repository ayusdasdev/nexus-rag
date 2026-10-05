from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select

from app.models.chunk import Chunk
from app.repositories.session import session_scope


@dataclass(frozen=True)
class ChunkRecord:
    id: UUID
    chunk_index: int
    text: str
    heading_path: str | None
    page: int | None
    token_count: int


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
        records = [
            ChunkRecord(
                id=row.id,
                chunk_index=row.chunk_index,
                text=row.text,
                heading_path=row.heading_path,
                page=row.page,
                token_count=row.token_count,
            )
            for row in result.scalars().all()
        ]
        return records, int(total or 0)
