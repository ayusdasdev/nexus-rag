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

from app.api.deps import CurrentUser, get_current_user
from app.core.config import get_settings
from app.repositories.blob_store import LocalBlobStore, get_blob_store
from app.repositories.document_repository import DocumentRecord
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
) -> DocumentService:
    return DocumentService(
        blob_store=blob_store,
        task_queue=task_queue,
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
    summary="Upload a document for ingestion",
)
async def upload_document(
    response: Response,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI DI pattern
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
            tenant_id=current_user.tenant_id,
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
    summary="Get a document's status",
)
async def get_document(
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> DocumentResponse:
    """Return a document in the caller's tenant. Other tenants' ids get 404, not 403."""
    try:
        document = await service.get(
            tenant_id=current_user.tenant_id, document_id=document_id
        )
    except DocumentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc
    return _to_response(document)


_LIMIT = Query(default=20, ge=1, le=100)
_OFFSET = Query(default=0, ge=0)


@router.get("", response_model=DocumentPage, summary="List the tenant's documents")
async def list_documents(
    limit: int = _LIMIT,
    offset: int = _OFFSET,
    current_user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> DocumentPage:
    """Newest first. Only documents in the caller's tenant."""
    records, total = await service.list_documents(
        tenant_id=current_user.tenant_id, limit=limit, offset=offset
    )
    return DocumentPage(
        items=[_to_response(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}/chunks",
    response_model=ChunkPage,
    summary="List a document's chunks",
)
async def list_chunks(
    document_id: UUID,
    limit: int = _LIMIT,
    offset: int = _OFFSET,
    current_user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> ChunkPage:
    """Chunks in chunk_index order. 404 if the document is not in the caller's tenant."""
    try:
        records, total = await service.list_chunks(
            tenant_id=current_user.tenant_id,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
    except DocumentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc
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
        offset=offset,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document, its chunks and its stored file",
)
async def delete_document(
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
    service: DocumentService = Depends(get_document_service),  # noqa: B008 - FastAPI DI pattern
) -> Response:
    """Removes the row (chunks cascade) and then the stored file. 404 for other tenants."""
    try:
        await service.delete(tenant_id=current_user.tenant_id, document_id=document_id)
    except DocumentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
