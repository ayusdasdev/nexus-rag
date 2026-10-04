from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from app.models.document import Document, DocumentStatus
from app.repositories.session import session_scope


class DuplicateDocument(Exception):
    pass


@dataclass(frozen=True)
class DocumentRecord:
    id: UUID
    tenant_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    error: str | None
    created_at: datetime


def _to_record(row: Document) -> DocumentRecord:
    return DocumentRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        filename=row.filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        status=row.status.value,
        error=row.error,
        created_at=row.created_at,
    )


async def create_document(
    *,
    tenant_id: UUID,
    uploaded_by: UUID,
    filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
) -> DocumentRecord:
    async with session_scope() as session:
        row = Document(
            tenant_id=tenant_id,
            uploaded_by=uploaded_by,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            status=DocumentStatus.uploaded,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise DuplicateDocument from exc
        await session.commit()
        return _to_record(row)


async def get_by_sha256(tenant_id: UUID, sha256: str) -> DocumentRecord | None:
    async with session_scope() as session:
        result = await session.execute(
            select(Document).where(
                Document.tenant_id == tenant_id, Document.sha256 == sha256
            )
        )
        row = result.scalars().first()
        return None if row is None else _to_record(row)


async def get_by_id(tenant_id: UUID, document_id: UUID) -> DocumentRecord | None:
    async with session_scope() as session:
        result = await session.execute(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == tenant_id
            )
        )
        row = result.scalars().first()
        return None if row is None else _to_record(row)


async def set_status(
    document_id: UUID, status: DocumentStatus, error: str | None = None
) -> None:
    async with session_scope() as session:
        row = await session.get(Document, document_id)
        if row is None:
            raise LookupError(str(document_id))
        row.status = status
        row.error = error
        await session.commit()


async def reset_failed_to_uploaded(document_id: UUID) -> bool:
    """Compare-and-set: succeeds only if the document is currently failed."""
    async with session_scope() as session:
        result = await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DocumentStatus.failed)
            .values(status=DocumentStatus.uploaded, error=None)
        )
        await session.commit()
        return cast(CursorResult[Any], result).rowcount > 0
