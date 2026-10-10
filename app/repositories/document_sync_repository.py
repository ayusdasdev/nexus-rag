from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from sqlalchemy import create_engine, delete, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import TransientError
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus

_CLAIMABLE = (DocumentStatus.uploaded, DocumentStatus.processing)
_EMBEDDABLE = (DocumentStatus.chunked, DocumentStatus.embedding)
_FAILABLE = (
    DocumentStatus.uploaded,
    DocumentStatus.processing,
    DocumentStatus.chunked,
    DocumentStatus.embedding,
)


@dataclass(frozen=True)
class ClaimedDocument:
    tenant_id: UUID
    sha256: str
    content_type: str


@lru_cache
def _engine() -> Engine:
    url = get_settings().database_url.replace(
        "postgresql+asyncpg", "postgresql+psycopg"
    )
    # hide_parameters: a DB error message never carries chunk text or other values into logs.
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def claim_for_processing(document_id: UUID) -> ClaimedDocument | None:
    """Move uploaded or processing to processing. None if the document is past that."""
    try:
        with Session(_engine()) as session, session.begin():
            row = session.execute(
                update(Document)
                .where(Document.id == document_id, Document.status.in_(_CLAIMABLE))
                .values(status=DocumentStatus.processing, status_updated_at=func.now())
                .returning(Document.tenant_id, Document.sha256, Document.content_type)
            ).first()
    except OperationalError as exc:
        raise TransientError(str(exc)) from exc
    if row is None:
        return None
    return ClaimedDocument(
        tenant_id=row.tenant_id, sha256=row.sha256, content_type=row.content_type
    )


def claim_for_embedding(document_id: UUID) -> ClaimedDocument | None:
    """Move chunked or embedding to embedding. None if the document is elsewhere."""
    try:
        with Session(_engine()) as session, session.begin():
            row = session.execute(
                update(Document)
                .where(Document.id == document_id, Document.status.in_(_EMBEDDABLE))
                .values(status=DocumentStatus.embedding, status_updated_at=func.now())
                .returning(Document.tenant_id, Document.sha256, Document.content_type)
            ).first()
    except OperationalError as exc:
        raise TransientError(str(exc)) from exc
    if row is None:
        return None
    return ClaimedDocument(
        tenant_id=row.tenant_id, sha256=row.sha256, content_type=row.content_type
    )


@dataclass(frozen=True)
class EmbedChunk:
    id: UUID
    chunk_index: int
    text: str
    heading_path: str | None


def load_chunks_for_embedding(document_id: UUID, tenant_id: UUID) -> list[EmbedChunk]:
    try:
        with Session(_engine()) as session:
            rows = session.execute(
                select(Chunk.id, Chunk.chunk_index, Chunk.text, Chunk.heading_path)
                .where(Chunk.document_id == document_id, Chunk.tenant_id == tenant_id)
                .order_by(Chunk.chunk_index)
            ).all()
    except OperationalError as exc:
        raise TransientError(str(exc)) from exc
    return [
        EmbedChunk(
            id=row.id,
            chunk_index=row.chunk_index,
            text=row.text,
            heading_path=row.heading_path,
        )
        for row in rows
    ]


def mark_ready(document_id: UUID) -> None:
    try:
        with Session(_engine()) as session, session.begin():
            session.execute(
                update(Document)
                .where(
                    Document.id == document_id,
                    Document.status == DocumentStatus.embedding,
                )
                .values(
                    status=DocumentStatus.ready,
                    error=None,
                    status_updated_at=func.now(),
                )
            )
    except OperationalError as exc:
        raise TransientError(str(exc)) from exc


def mark_failed(document_id: UUID, error: str) -> None:
    try:
        with Session(_engine()) as session, session.begin():
            session.execute(
                update(Document)
                .where(Document.id == document_id, Document.status.in_(_FAILABLE))
                .values(
                    status=DocumentStatus.failed,
                    error=error,
                    status_updated_at=func.now(),
                )
            )
    except OperationalError as exc:
        raise TransientError(str(exc)) from exc


@dataclass(frozen=True)
class ChunkRow:
    id: UUID
    chunk_index: int
    text: str
    heading_path: str | None
    page: int | None
    token_count: int


def replace_chunks(document_id: UUID, tenant_id: UUID, rows: list[ChunkRow]) -> None:
    """Replace the document's chunks and mark it chunked, in one transaction."""
    try:
        with Session(_engine()) as session, session.begin():
            session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            if rows:
                session.execute(
                    insert(Chunk),
                    [
                        {
                            "id": row.id,
                            "tenant_id": tenant_id,
                            "document_id": document_id,
                            "chunk_index": row.chunk_index,
                            "text": row.text,
                            "heading_path": row.heading_path,
                            "page": row.page,
                            "token_count": row.token_count,
                        }
                        for row in rows
                    ],
                )
            session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status=DocumentStatus.chunked,
                    error=None,
                    status_updated_at=func.now(),
                )
            )
    except OperationalError as exc:
        raise TransientError(str(exc)) from exc
