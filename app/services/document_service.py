import dataclasses
import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID

from app.models.document import DocumentStatus
from app.repositories import document_repository
from app.repositories.blob_store import LocalBlobStore
from app.repositories.document_repository import DocumentRecord, DuplicateDocument
from app.services.file_validation import detect_content_type

_READ_CHUNK_BYTES = 64 * 1024
_MAX_FILENAME_CHARS = 512


class ByteSource(Protocol):
    async def read(self, size: int) -> bytes: ...


class TaskQueue(Protocol):
    async def enqueue_ingest(self, document_id: UUID) -> None: ...


class FileTooLarge(Exception):
    pass


class EmptyFile(Exception):
    pass


class UnsupportedFileType(Exception):
    pass


class DocumentNotFound(Exception):
    pass


class EnqueueFailed(Exception):
    pass


@dataclass(frozen=True)
class UploadResult:
    document: DocumentRecord
    queued: bool


def _display_filename(raw: str | None) -> str:
    base = PurePosixPath((raw or "").replace("\\", "/")).name
    printable = "".join(ch for ch in base if ch.isprintable()).strip()
    return (printable or "upload")[:_MAX_FILENAME_CHARS]


async def _read_capped(source: ByteSource, max_bytes: int) -> bytes:
    buffer = bytearray()
    while chunk := await source.read(_READ_CHUNK_BYTES):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise FileTooLarge
    return bytes(buffer)


class DocumentService:
    def __init__(
        self,
        *,
        blob_store: LocalBlobStore,
        task_queue: TaskQueue,
        max_upload_bytes: int,
    ) -> None:
        self._blob_store = blob_store
        self._task_queue = task_queue
        self._max_upload_bytes = max_upload_bytes

    async def upload(
        self,
        *,
        tenant_id: UUID,
        uploaded_by: UUID,
        filename: str | None,
        source: ByteSource,
    ) -> UploadResult:
        data = await _read_capped(source, self._max_upload_bytes)
        if not data:
            raise EmptyFile

        content_type = detect_content_type(data)
        if content_type is None:
            raise UnsupportedFileType

        sha256 = hashlib.sha256(data).hexdigest()
        existing = await document_repository.get_by_sha256(tenant_id, sha256)
        if existing is not None:
            if existing.status == DocumentStatus.failed.value and (
                await document_repository.reset_failed_to_uploaded(existing.id)
            ):
                await self._enqueue(existing.id)
                reset = dataclasses.replace(existing, status="uploaded", error=None)
                return UploadResult(document=reset, queued=True)
            return UploadResult(document=existing, queued=False)

        await self._blob_store.save(tenant_id, sha256, data)
        try:
            created = await document_repository.create_document(
                tenant_id=tenant_id,
                uploaded_by=uploaded_by,
                filename=_display_filename(filename),
                content_type=content_type,
                size_bytes=len(data),
                sha256=sha256,
            )
        except DuplicateDocument:
            # A concurrent upload with the same bytes won the race.
            winner = await document_repository.get_by_sha256(tenant_id, sha256)
            if winner is None:
                raise
            return UploadResult(document=winner, queued=False)

        await self._enqueue(created.id)
        return UploadResult(document=created, queued=True)

    async def _enqueue(self, document_id: UUID) -> None:
        try:
            await self._task_queue.enqueue_ingest(document_id)
        except Exception as exc:
            # The row is already committed; leaving it "uploaded" would strand it.
            await document_repository.set_status(
                document_id, DocumentStatus.failed, error="could not enqueue"
            )
            raise EnqueueFailed from exc

    async def get(self, *, tenant_id: UUID, document_id: UUID) -> DocumentRecord:
        document = await document_repository.get_by_id(tenant_id, document_id)
        if document is None:
            raise DocumentNotFound
        return document
