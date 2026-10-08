import hashlib
import uuid
from uuid import UUID

import pytest

from app.core.ids import chunk_id
from app.models.chunk import Chunk
from app.repositories import auth_repository, chunk_repository, document_repository
from app.repositories.session import session_scope

# Shares one event loop with the global SQLAlchemy engine (see test_auth.py).
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def _tenant_with_document() -> tuple[UUID, UUID]:
    tenant, user = await auth_repository.create_tenant_and_admin_user(
        f"tenant-{uuid.uuid4().hex}", f"user-{uuid.uuid4().hex}@example.com", "hash"
    )
    sha = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    document = await document_repository.create_document(
        tenant_id=tenant.id,
        uploaded_by=user.id,
        filename="notes.md",
        content_type="text/markdown",
        size_bytes=10,
        sha256=sha,
    )
    return tenant.id, document.id


async def _make_chunk(
    tenant_id: UUID, document_id: UUID, index: int, text: str
) -> UUID:
    cid = chunk_id(document_id, index)
    async with session_scope() as session:
        session.add(
            Chunk(
                id=cid,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=index,
                text=text,
                heading_path=None,
                page=None,
                token_count=len(text.split()),
            )
        )
        await session.commit()
    return cid


async def test_fetch_chunks_returns_matching_chunks_for_the_tenant() -> None:
    tenant_id, document_id = await _tenant_with_document()
    first = await _make_chunk(tenant_id, document_id, 0, "alpha")
    second = await _make_chunk(tenant_id, document_id, 1, "beta")

    records = await chunk_repository.fetch_chunks(tenant_id, [first, second])

    assert {record.id for record in records} == {first, second}


async def test_fetch_chunks_drops_ids_belonging_to_another_tenant() -> None:
    tenant_a, doc_a = await _tenant_with_document()
    tenant_b, doc_b = await _tenant_with_document()
    chunk_a = await _make_chunk(tenant_a, doc_a, 0, "mine")
    chunk_b = await _make_chunk(tenant_b, doc_b, 0, "not mine")

    records = await chunk_repository.fetch_chunks(tenant_a, [chunk_a, chunk_b])

    assert {record.id for record in records} == {chunk_a}


async def test_fetch_chunks_ignores_an_id_that_does_not_exist_at_all() -> None:
    tenant_id, document_id = await _tenant_with_document()
    real = await _make_chunk(tenant_id, document_id, 0, "alpha")

    records = await chunk_repository.fetch_chunks(tenant_id, [real, uuid.uuid4()])

    assert {record.id for record in records} == {real}


async def test_fetch_chunks_of_empty_ids_returns_empty() -> None:
    tenant_id, _document_id = await _tenant_with_document()

    assert await chunk_repository.fetch_chunks(tenant_id, []) == []
