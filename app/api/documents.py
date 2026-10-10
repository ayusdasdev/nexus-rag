from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app.api.deps import CurrentUser, get_current_user, get_tenant_id
from app.api.pagination import AFTER, index_key, page, time_cursor_key, time_key
from app.api.rate_limit import limit_default, limit_upload
from app.core.config import get_settings
from app.core.errors import TransientError
from app.repositories.blob_store import LocalBlobStore, get_blob_store
from app.repositories.document_repository import DocumentRecord
from app.repositories.vector_store import VectorStore, get_vector_store
from app.schemas.documents import (
    ChunkPage,
    ChunkResponse,
    DocumentPage,
    DocumentResponse,
)
from app.services.document_service import (
    DocumentNotFound,
    DocumentService,
    EmptyFile,
    EnqueueFailed,
    FileTooLarge,
    TaskQueue,
    UnsupportedFileType,
)
from app.workers.queue import CeleryTaskQueue

router = APIRouter(prefix="/documents", tags=["documents"])


def get_task_queue() -> TaskQueue:
    return CeleryTaskQueue()


def get_document_service(
    blob_store: LocalBlobStore = Depends(get_blob_store),  # noqa: B008 - FastAPI DI pattern
    task_queue: TaskQueue = Depends(get_task_queue),  # noqa: B008 - FastAPI DI pattern
    vectors: VectorStore = Depends(get_vector_store),  # noqa: B008 - FastAPI DI pattern
) -> DocumentService:
    return DocumentService(
        blob_store=blob_store,
        task_queue=task_queue,
        vectors=vectors,
        max_upload_bytes=get_settings().max_upload_mb * 1024 * 1024,
    )


def _to_response(document: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        status=document.status,
        error=document.error,
        created_at=document.created_at,
    )


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_upload)],
    summary="Upload a document for ingestion",
)
async def upload_document(
    response: Response,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI DI pattern
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    current_user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> DocumentResponse:
    """Upload a PDF, HTML, Markdown or plain-text file.

    Returns 202 with status 'uploaded' and enqueues ingestion. If the same bytes were
    already uploaded by this tenant, returns the existing document with 200 and does not
    re-enqueue. Type is detected from content, not from the filename or Content-Type.
    """
    try:
        result = await service.upload(
            tenant_id=tenant_id,
            uploaded_by=current_user.id,
            filename=file.filename,
            source=file,
        )
    except FileTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File exceeds the upload size limit",
        ) from exc
    except UnsupportedFileType as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type",
        ) from exc
    except EnqueueFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion queue unavailable",
        ) from exc
    except EmptyFile as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="File is empty"
        ) from exc

    if not result.queued:
        response.status_code = status.HTTP_200_OK
    return _to_response(result.document)


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    dependencies=[Depends(limit_default)],
    summary="Get a document's status",
)
async def get_document(
    document_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> DocumentResponse:
    """Return a document in the caller's tenant. Other tenants' ids get 404, not 403."""
    try:
        document = await service.get(tenant_id=tenant_id, document_id=document_id)
    except DocumentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc
    return _to_response(document)


_LIMIT = Query(default=20, ge=1, le=100)


@router.get(
    "",
    response_model=DocumentPage,
    dependencies=[Depends(limit_default)],
    summary="List the tenant's documents",
)
async def list_documents(
    limit: int = _LIMIT,
    after: str | None = AFTER,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> DocumentPage:
    """Newest first, one cursor page at a time. Only documents in the caller's tenant."""
    scope = f"documents:{tenant_id}"
    rows, total = await service.list_documents(
        tenant_id=tenant_id, limit=limit + 1, after=time_key(after, scope)
    )
    records, next_cursor = page(
        rows, limit, scope, lambda r: time_cursor_key(r.created_at, r.id)
    )
    return DocumentPage(
        items=[_to_response(record) for record in records],
        total=total,
        limit=limit,
        next_cursor=next_cursor,
    )


@router.get(
    "/{document_id}/chunks",
    response_model=ChunkPage,
    dependencies=[Depends(limit_default)],
    summary="List a document's chunks",
)
async def list_chunks(
    document_id: UUID,
    limit: int = _LIMIT,
    after: str | None = AFTER,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> ChunkPage:
    """Chunks in chunk_index order, one cursor page at a time. 404 if the document is not
    in the caller's tenant."""
    scope = f"chunks:{tenant_id}:{document_id}"
    try:
        rows, total = await service.list_chunks(
            tenant_id=tenant_id,
            document_id=document_id,
            limit=limit + 1,
            after=index_key(after, scope),
        )
    except DocumentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc
    records, next_cursor = page(rows, limit, scope, lambda r: [r.chunk_index])
    return ChunkPage(
        items=[
            ChunkResponse(
                id=record.id,
                chunk_index=record.chunk_index,
                text=record.text,
                heading_path=record.heading_path,
                page=record.page,
                token_count=record.token_count,
            )
            for record in records
        ],
        total=total,
        limit=limit,
        next_cursor=next_cursor,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_default)],
    summary="Delete a document, its chunks and its stored file",
)
async def delete_document(
    document_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> Response:
    """Removes the row (chunks cascade) and then the stored file. 404 for other tenants."""
    try:
        await service.delete(tenant_id=tenant_id, document_id=document_id)
    except DocumentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc
    except TransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store is temporarily unavailable; retry the delete",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
