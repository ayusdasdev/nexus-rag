import hashlib
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.api.documents import get_task_queue
from app.main import app
from app.models.document import DocumentStatus
from app.repositories import document_repository
from app.repositories.blob_store import LocalBlobStore, get_blob_store
from app.schemas.documents import DocumentResponse

# Shares one event loop with the global SQLAlchemy engine (see test_auth.py).
pytestmark = pytest.mark.asyncio(loop_scope="session")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class FakeTaskQueue:
    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue_ingest(self, document_id: uuid.UUID) -> None:
        self.enqueued.append(document_id)


@pytest.fixture
def queue() -> FakeTaskQueue:
    fake = FakeTaskQueue()
    app.dependency_overrides[get_task_queue] = lambda: fake
    return fake


@pytest.fixture
def blob_root(tmp_path: Path) -> Path:
    store = LocalBlobStore(tmp_path)
    app.dependency_overrides[get_blob_store] = lambda: store
    return tmp_path


async def _signup(client: AsyncClient) -> dict[str, Any]:
    response = await client.post(
        "/auth/signup",
        json={
            "tenant_name": f"tenant-{uuid.uuid4().hex}",
            "email": f"user-{uuid.uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _upload(
    client: AsyncClient,
    token: str | None,
    data: bytes,
    filename: str = "doc.pdf",
) -> Any:
    headers = _auth(token) if token else {}
    return await client.post(
        "/v1/documents",
        files={"file": (filename, data, "application/octet-stream")},
        headers=headers,
    )


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n" + uuid.uuid4().bytes


async def test_upload_returns_202_and_uploaded_status(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)
    data = _pdf_bytes()

    response = await _upload(client, signup["access_token"], data)

    assert response.status_code == 202
    body = DocumentResponse.model_validate(response.json())
    assert body.filename == "doc.pdf"
    assert body.content_type == "application/pdf"
    assert body.size_bytes == len(data)
    assert body.sha256 == hashlib.sha256(data).hexdigest()
    assert body.status == "uploaded"
    assert body.error is None
    assert queue.enqueued == [body.id]


async def test_upload_duplicate_returns_existing_document_with_200(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)
    token = signup["access_token"]
    data = _pdf_bytes()

    first = await _upload(client, token, data)
    second = await _upload(client, token, data)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(queue.enqueued) == 1


async def test_upload_without_token_returns_401(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    response = await _upload(client, None, _pdf_bytes())

    assert response.status_code == 401
    assert queue.enqueued == []


async def test_upload_over_size_limit_returns_413(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)
    oversized = b"%PDF-" + b"0" * MAX_UPLOAD_BYTES

    response = await _upload(client, signup["access_token"], oversized)

    assert response.status_code == 413
    assert queue.enqueued == []
    assert list(blob_root.rglob("*")) == []


async def test_upload_unsupported_binary_returns_415(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)

    response = await _upload(
        client, signup["access_token"], b"\x89PNG\r\n\x1a\n\x00\x00"
    )

    assert response.status_code == 415
    assert queue.enqueued == []


async def test_upload_text_named_pdf_is_classified_by_content(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)

    response = await _upload(
        client, signup["access_token"], b"just some words", filename="evil.pdf"
    )

    assert response.status_code == 202
    assert response.json()["content_type"] == "text/plain"


async def test_upload_empty_file_returns_422(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)

    response = await _upload(client, signup["access_token"], b"")

    assert response.status_code == 422
    assert queue.enqueued == []


async def test_upload_stores_under_generated_path_not_client_filename(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)
    tenant_id = signup["user"]["tenant_id"]
    data = _pdf_bytes()

    response = await _upload(
        client, signup["access_token"], data, filename="../../secret-name.pdf"
    )

    assert response.status_code == 202
    stored = [p for p in blob_root.rglob("*") if p.is_file()]
    assert len(stored) == 1
    relative = stored[0].relative_to(blob_root)
    assert relative.parts == (tenant_id, hashlib.sha256(data).hexdigest())


async def test_get_own_document_returns_200(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)
    token = signup["access_token"]
    created = await _upload(client, token, _pdf_bytes())

    response = await client.get(
        f"/v1/documents/{created.json()['id']}", headers=_auth(token)
    )

    assert response.status_code == 200
    assert DocumentResponse.model_validate(response.json()).status == "uploaded"


async def test_get_document_of_other_tenant_returns_404(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    tenant_a = await _signup(client)
    tenant_b = await _signup(client)
    created = await _upload(client, tenant_a["access_token"], _pdf_bytes())

    response = await client.get(
        f"/v1/documents/{created.json()['id']}",
        headers=_auth(tenant_b["access_token"]),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


async def test_get_document_without_token_returns_401(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    response = await client.get(f"/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 401


async def test_duplicate_of_failed_document_is_requeued_with_202(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)
    token = signup["access_token"]
    data = _pdf_bytes()
    first = await _upload(client, token, data)
    doc_id = uuid.UUID(first.json()["id"])
    await document_repository.set_status(doc_id, DocumentStatus.failed, error="boom")

    second = await _upload(client, token, data)

    assert second.status_code == 202
    body = DocumentResponse.model_validate(second.json())
    assert body.id == doc_id
    assert body.status == "uploaded"
    assert body.error is None
    assert queue.enqueued == [doc_id, doc_id]


@pytest.mark.parametrize(
    "status",
    [
        DocumentStatus.uploaded,
        DocumentStatus.processing,
        DocumentStatus.chunked,
        DocumentStatus.ready,
    ],
)
async def test_duplicate_of_non_failed_document_returns_200_without_requeue(
    client: AsyncClient,
    queue: FakeTaskQueue,
    blob_root: Path,
    status: DocumentStatus,
) -> None:
    signup = await _signup(client)
    token = signup["access_token"]
    data = _pdf_bytes()
    first = await _upload(client, token, data)
    doc_id = uuid.UUID(first.json()["id"])
    await document_repository.set_status(doc_id, status)

    second = await _upload(client, token, data)

    assert second.status_code == 200
    assert second.json()["status"] == status.value
    assert queue.enqueued == [doc_id]


class BrokenTaskQueue:
    async def enqueue_ingest(self, document_id: uuid.UUID) -> None:
        raise ConnectionError("broker unreachable")


@pytest.fixture
def broken_queue() -> BrokenTaskQueue:
    broken = BrokenTaskQueue()
    app.dependency_overrides[get_task_queue] = lambda: broken
    return broken


async def test_enqueue_failure_marks_document_failed_and_returns_503(
    client: AsyncClient, broken_queue: BrokenTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)
    tenant_id = uuid.UUID(signup["user"]["tenant_id"])
    data = _pdf_bytes()

    response = await _upload(client, signup["access_token"], data)

    assert response.status_code == 503
    stored = await document_repository.get_by_sha256(
        tenant_id, hashlib.sha256(data).hexdigest()
    )
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "could not enqueue"


async def test_enqueue_failure_on_requeue_marks_document_failed_and_returns_503(
    client: AsyncClient,
    queue: FakeTaskQueue,
    blob_root: Path,
) -> None:
    signup = await _signup(client)
    tenant_id = uuid.UUID(signup["user"]["tenant_id"])
    token = signup["access_token"]
    data = _pdf_bytes()
    first = await _upload(client, token, data)
    doc_id = uuid.UUID(first.json()["id"])
    await document_repository.set_status(doc_id, DocumentStatus.failed, error="boom")
    broken = BrokenTaskQueue()
    app.dependency_overrides[get_task_queue] = lambda: broken

    response = await _upload(client, token, data)

    assert response.status_code == 503
    stored = await document_repository.get_by_sha256(
        tenant_id, hashlib.sha256(data).hexdigest()
    )
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "could not enqueue"


EXPECTED_RESPONSE_FIELDS = {
    "id",
    "filename",
    "content_type",
    "size_bytes",
    "sha256",
    "status",
    "error",
    "created_at",
}


async def test_document_response_exposes_exact_fields_and_no_storage_path(
    client: AsyncClient, queue: FakeTaskQueue, blob_root: Path
) -> None:
    signup = await _signup(client)

    response = await _upload(client, signup["access_token"], _pdf_bytes())

    assert set(response.json()) == EXPECTED_RESPONSE_FIELDS
    assert set(DocumentResponse.model_fields) == EXPECTED_RESPONSE_FIELDS
    assert not any("path" in name or "storage" in name for name in response.json())
