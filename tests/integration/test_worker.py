import hashlib
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.core.errors import TransientError
from app.core.ids import chunk_id
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.providers.tokenizer import is_cached
from app.repositories import auth_repository, document_repository
from app.repositories.blob_store import LocalBlobStore
from app.repositories.session import session_scope
from app.workers import tasks

# Shares one event loop with the global SQLAlchemy engine (see test_auth.py).
pytestmark = pytest.mark.asyncio(loop_scope="session")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
needs_tokenizer = pytest.mark.skipif(
    not is_cached(), reason="BGE tokenizer not cached; run make fetch-models"
)


async def _new_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    content_type: str,
) -> uuid.UUID:
    data = source.read_bytes()
    tenant, user = await auth_repository.create_tenant_and_admin_user(
        f"tenant-{uuid.uuid4().hex}", f"user-{uuid.uuid4().hex}@example.com", "hash"
    )
    sha = hashlib.sha256(data).hexdigest()
    store = LocalBlobStore(tmp_path)
    await store.save(tenant.id, sha, data)
    monkeypatch.setattr(tasks, "get_blob_store", lambda: store)
    document = await document_repository.create_document(
        tenant_id=tenant.id,
        uploaded_by=user.id,
        filename=source.name,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha,
    )
    return document.id


async def _row(document_id: uuid.UUID) -> Document:
    async with session_scope() as session:
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        row: Document = result.scalars().one()
        return row


async def _chunks(document_id: uuid.UUID) -> list[Chunk]:
    async with session_scope() as session:
        result = await session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
        )
        return list(result.scalars().all())


@needs_tokenizer
@pytest.mark.parametrize(
    ("fixture", "content_type"),
    [
        ("nested_headings.md", "text/plain"),
        ("nav_footer.html", "text/html"),
        ("two_column_table.pdf", "application/pdf"),
    ],
)
async def test_end_to_end_chunks_each_fixture_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture: str, content_type: str
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / fixture, content_type
    )

    result = tasks.process_document.apply(args=[str(document_id)])

    assert result.state == "SUCCESS"
    row = await _row(document_id)
    assert row.status == DocumentStatus.chunked
    assert row.error is None
    chunks = await _chunks(document_id)
    assert chunks
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.id == chunk_id(document_id, c.chunk_index) for c in chunks)
    assert all(c.token_count <= 350 for c in chunks)


@needs_tokenizer
async def test_running_twice_gives_identical_ids_and_no_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    tasks.process_document.apply(args=[str(document_id)])
    first = await _chunks(document_id)

    await document_repository.set_status(document_id, DocumentStatus.uploaded)
    tasks.process_document.apply(args=[str(document_id)])
    second = await _chunks(document_id)

    assert [(c.id, c.text) for c in first] == [(c.id, c.text) for c in second]
    assert len({c.id for c in second}) == len(second)


async def test_scanned_pdf_fails_with_readable_message_and_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "scanned.pdf", "application/pdf"
    )

    result = tasks.process_document.apply(args=[str(document_id)])

    assert result.state == "SUCCESS"
    row = await _row(document_id)
    assert row.status == DocumentStatus.failed
    assert row.error is not None
    assert row.error.startswith("No extractable text")
    assert await _chunks(document_id) == []


async def test_transient_error_retries_three_times_then_marks_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    calls: list[Any] = []

    def flaky(path: Path, content_type: str, tokenizer: Any, strategy: str) -> None:
        calls.append(path)
        raise TransientError("database temporarily unavailable")

    monkeypatch.setattr(tasks, "chunk_document", flaky)

    result = tasks.process_document.apply(args=[str(document_id)])

    assert result.state == "FAILURE"
    assert len(calls) == 4  # first attempt + 3 retries
    row = await _row(document_id)
    assert row.status == DocumentStatus.failed
    assert row.error is not None
    assert row.error.startswith("TransientError")


async def test_reserved_parent_child_strategy_fails_with_readable_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(chunk_strategy="parent_child")
    )

    tasks.process_document.apply(args=[str(document_id)])

    row = await _row(document_id)
    assert row.status == DocumentStatus.failed
    assert row.error == "Chunk strategy 'parent_child' is not available yet."


async def test_document_already_past_processing_is_not_reprocessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    await document_repository.set_status(document_id, DocumentStatus.chunked)
    calls: list[Any] = []

    def record(*args: Any) -> list[Any]:
        calls.append(args)
        return []

    monkeypatch.setattr(tasks, "chunk_document", record)

    tasks.process_document.apply(args=[str(document_id)])

    assert calls == []
    row = await _row(document_id)
    assert row.status == DocumentStatus.chunked
    assert row.error is None
