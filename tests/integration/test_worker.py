import hashlib
import inspect
import uuid
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.core.errors import TransientError
from app.core.ids import chunk_id
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.providers import embeddings
from app.providers.embeddings import FakeEmbedder
from app.providers.tokenizer import is_cached
from app.repositories import auth_repository, document_repository
from app.repositories.blob_store import LocalBlobStore
from app.repositories.session import session_scope
from app.repositories.vector_store import VectorPoint
from app.workers import tasks

# Shares one event loop with the global SQLAlchemy engine (see test_auth.py).
pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.usefixtures("embedding_stack"),
]

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
    assert row.status == DocumentStatus.ready
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
    assert row.status == DocumentStatus.ready
    assert row.error is None


@pytest.fixture
def empty_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    cache = tmp_path_factory.mktemp("empty_fastembed_cache")
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(fastembed_cache_dir=str(cache)),
    )
    return cache


def _doc_point_ids(
    store: Any, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> set[uuid.UUID]:
    hits = store.search_dense(tenant_id, FakeEmbedder().embed_documents(["x"])[0], 1000)
    return {hit.chunk_id for hit in hits if hit.document_id == document_id}


async def _tenant_of(document_id: uuid.UUID) -> uuid.UUID:
    row = await _row(document_id)
    tenant_id: uuid.UUID = row.tenant_id
    return tenant_id


async def test_chunked_document_is_embedded_upserted_and_marked_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )

    result = tasks.process_document.apply(args=[str(document_id)])

    assert result.state == "SUCCESS"
    tenant_id = await _tenant_of(document_id)
    chunks = await _chunks(document_id)
    assert (await _row(document_id)).status == DocumentStatus.ready
    assert _doc_point_ids(embedding_stack, tenant_id, document_id) == {
        c.id for c in chunks
    }


async def test_embedding_status_document_is_reclaimed_and_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    tasks.process_document.apply(args=[str(document_id)])
    await document_repository.set_status(document_id, DocumentStatus.embedding)

    tasks.process_document.apply(args=[str(document_id)])

    assert (await _row(document_id)).status == DocumentStatus.ready


async def test_rerun_is_safe_and_leaves_no_duplicate_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    tasks.process_document.apply(args=[str(document_id)])
    tenant_id = await _tenant_of(document_id)
    first = _doc_point_ids(embedding_stack, tenant_id, document_id)

    await document_repository.set_status(document_id, DocumentStatus.chunked)
    tasks.process_document.apply(args=[str(document_id)])

    assert _doc_point_ids(embedding_stack, tenant_id, document_id) == first
    assert (await _row(document_id)).status == DocumentStatus.ready


async def test_points_from_an_earlier_run_that_are_no_longer_current_are_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    tasks.process_document.apply(args=[str(document_id)])
    tenant_id = await _tenant_of(document_id)
    stale = VectorPoint(
        chunk_id=chunk_id(document_id, 999),
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=999,
        dense=FakeEmbedder().embed_documents(["stale"])[0],
        sparse_indices=[1],
        sparse_values=[1.0],
    )
    embedding_stack.upsert_points([stale])
    await document_repository.set_status(document_id, DocumentStatus.chunked)

    tasks.process_document.apply(args=[str(document_id)])

    assert chunk_id(document_id, 999) not in _doc_point_ids(
        embedding_stack, tenant_id, document_id
    )


async def test_dimension_mismatch_fails_permanently_with_a_readable_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )

    class WrongSize(FakeEmbedder):
        dim = 32

        def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            return [[0.0] * 512 for _ in texts]

    monkeypatch.setattr(tasks, "get_embedder", WrongSize)

    result = tasks.process_document.apply(args=[str(document_id)])

    assert result.state == "SUCCESS"  # permanent: no retry
    row = await _row(document_id)
    assert row.status == DocumentStatus.failed
    assert row.error is not None
    assert "expected 32, got 512" in row.error


async def test_missing_model_fails_with_make_fetch_models_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty_cache: Path
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    monkeypatch.setattr(tasks, "get_embedder", embeddings.BgeEmbedder)

    result = tasks.process_document.apply(args=[str(document_id)])

    assert result.state == "SUCCESS"
    row = await _row(document_id)
    assert row.status == DocumentStatus.failed
    assert row.error is not None
    assert "make fetch-models" in row.error


async def test_transient_qdrant_error_retries_three_times_then_marks_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    calls: list[int] = []

    def unreachable(points: Any) -> None:
        calls.append(1)
        raise TransientError("qdrant unreachable")

    monkeypatch.setattr(embedding_stack, "upsert_points", unreachable)

    result = tasks.process_document.apply(args=[str(document_id)])

    assert result.state == "FAILURE"
    assert len(calls) == 4
    row = await _row(document_id)
    assert row.status == DocumentStatus.failed
    assert row.error is not None
    assert row.error.startswith("TransientError")


async def test_transient_qdrant_error_then_success_resumes_from_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    real_upsert = embedding_stack.upsert_points
    failures = [TransientError("blip")]

    def flaky(points: Any) -> None:
        if failures:
            raise failures.pop()
        real_upsert(points)

    monkeypatch.setattr(embedding_stack, "upsert_points", flaky)

    result = tasks.process_document.apply(args=[str(document_id)])

    assert result.state == "SUCCESS"
    assert (await _row(document_id)).status == DocumentStatus.ready


async def test_heading_path_is_prepended_only_when_flag_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    seen: list[str] = []

    class Recording(FakeEmbedder):
        def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            seen.extend(texts)
            return super().embed_documents(texts)

    monkeypatch.setattr(tasks, "get_embedder", Recording)
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: SimpleNamespace(chunk_strategy="structure", embed_with_heading=True),
    )

    tasks.process_document.apply(args=[str(document_id)])

    chunks = await _chunks(document_id)
    expected = [
        f"{c.heading_path}\n{c.text}" if c.heading_path else c.text for c in chunks
    ]
    assert seen == expected
    assert any("\n" in text for text in expected)


async def test_embedding_batches_respect_the_batch_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "long_document.md", "text/plain"
    )
    sizes: list[int] = []

    class Counting(FakeEmbedder):
        def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            sizes.append(len(texts))
            return super().embed_documents(texts)

    monkeypatch.setattr(tasks, "get_embedder", Counting)
    monkeypatch.setattr(tasks, "EMBED_BATCH_SIZE", 2)

    tasks.process_document.apply(args=[str(document_id)])

    chunks = await _chunks(document_id)
    assert len(chunks) > 2
    assert max(sizes) <= 2
    assert sum(sizes) == len(chunks)


async def test_worker_takes_only_the_document_id_from_the_task_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedding_stack: Any
) -> None:
    assert list(inspect.signature(tasks.process_document.run).parameters) == [
        "document_id"
    ]

    document_id = await _new_document(
        tmp_path, monkeypatch, FIXTURES / "nested_headings.md", "text/plain"
    )
    tasks.process_document.apply(args=[str(document_id)])

    tenant_id = await _tenant_of(document_id)
    other_tenant = uuid.uuid4()
    assert _doc_point_ids(embedding_stack, tenant_id, document_id)
    assert _doc_point_ids(embedding_stack, other_tenant, document_id) == set()
