import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from qdrant_client import QdrantClient

from app.core.config import get_settings
from app.main import app
from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder
from app.repositories.vector_store import VectorStore
from app.workers import tasks

if TYPE_CHECKING:
    from app.providers.llm import FakeLLM


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def embedding_stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[VectorStore]:
    """Worker embedding wired to fakes and a uniquely named real-Qdrant collection."""
    client = QdrantClient(url=get_settings().qdrant_url)
    name = f"test_{uuid.uuid4().hex}"
    store = VectorStore(client, dim=FakeEmbedder.dim, collection=name)
    monkeypatch.setattr(tasks, "get_vector_store", lambda: store)
    monkeypatch.setattr(tasks, "get_embedder", FakeEmbedder)
    monkeypatch.setattr(tasks, "get_sparse_embedder", FakeSparseEmbedder)
    try:
        yield store
    finally:
        if client.collection_exists(name):
            client.delete_collection(name)
        client.close()


# --- M6: a seeded RAG stack with fakes, for conversation and IDOR tests -----------


@dataclass
class Caller:
    """An authenticated user: their bearer headers, ids and seeded chunk ids."""

    headers: dict[str, str]
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    chunk_ids: list[str]


TEXTS = [
    "Charging the widget takes two hours from empty.",
    "Battery calibration: drain fully, then charge without interruption.",
    "Warranty claims need the original receipt.",
]


@pytest.fixture
def rag_stack(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[VectorStore]:
    """Fake embedders/reranker, a per-test Qdrant collection, no queue, a temp blob store."""
    from app.api.documents import get_task_queue
    from app.providers import embeddings
    from app.providers import reranker as reranker_module
    from app.repositories.blob_store import LocalBlobStore, get_blob_store
    from app.repositories.vector_store import get_vector_store

    class _Queue:
        async def enqueue_ingest(self, document_id: uuid.UUID) -> None:
            return None

    fake = SimpleNamespace(embedder="fake")
    monkeypatch.setattr(embeddings, "get_settings", lambda: fake)
    monkeypatch.setattr(reranker_module, "get_settings", lambda: fake)
    for cached in (
        embeddings.get_embedder,
        embeddings.get_sparse_embedder,
        reranker_module.get_reranker,
    ):
        cached.cache_clear()
    client = QdrantClient(url=get_settings().qdrant_url)
    name = f"test_{uuid.uuid4().hex}"
    store = VectorStore(client, dim=FakeEmbedder.dim, collection=name)
    store.ensure_collection()
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_task_queue] = lambda: _Queue()
    app.dependency_overrides[get_blob_store] = lambda: LocalBlobStore(tmp_path)
    try:
        yield store
    finally:
        for dependency in (get_vector_store, get_task_queue, get_blob_store):
            app.dependency_overrides.pop(dependency, None)
        for cached in (
            embeddings.get_embedder,
            embeddings.get_sparse_embedder,
            reranker_module.get_reranker,
        ):
            cached.cache_clear()
        if client.collection_exists(name):
            client.delete_collection(name)
        client.close()


@pytest.fixture
def fake_llm() -> Iterator["FakeLLM"]:
    """FakeLLM answering "Two hours [1]." for every chat and conversation request."""
    from app.api.chat import get_chat_llm
    from app.providers.llm import FakeLLM

    llm = FakeLLM(["Two hours ", "[1]."])
    app.dependency_overrides[get_chat_llm] = lambda: llm
    try:
        yield llm
    finally:
        app.dependency_overrides.pop(get_chat_llm, None)


async def _seed_document(
    client: AsyncClient, store: VectorStore, caller: Caller
) -> list[str]:
    from app.core.ids import chunk_id
    from app.models.chunk import Chunk
    from app.models.document import DocumentStatus
    from app.repositories import document_repository
    from app.repositories.session import session_scope
    from app.repositories.vector_store import VectorPoint

    upload = await client.post(
        "/v1/documents",
        headers=caller.headers,
        files={
            "file": (
                f"{uuid.uuid4().hex}.md",
                "\n\n".join(TEXTS).encode(),
                "text/markdown",
            )
        },
    )
    assert upload.status_code in (200, 202), upload.text
    document_id = uuid.UUID(upload.json()["id"])
    await document_repository.set_status(document_id, DocumentStatus.ready)
    ids = [chunk_id(document_id, index) for index in range(len(TEXTS))]
    async with session_scope() as session:
        for index, text in enumerate(TEXTS):
            session.add(
                Chunk(
                    id=ids[index],
                    tenant_id=caller.tenant_id,
                    document_id=document_id,
                    chunk_index=index,
                    text=text,
                    heading_path=None,
                    page=None,
                    token_count=len(text.split()),
                )
            )
        await session.commit()
    dense = FakeEmbedder().embed_documents(TEXTS)
    sparse = FakeSparseEmbedder().embed_documents(TEXTS)
    store.upsert_points(
        [
            VectorPoint(
                chunk_id=ids[index],
                tenant_id=caller.tenant_id,
                document_id=document_id,
                chunk_index=index,
                dense=dense[index],
                sparse_indices=sparse[index].indices,
                sparse_values=sparse[index].values,
            )
            for index in range(len(TEXTS))
        ]
    )
    return [str(i) for i in ids]


@pytest.fixture
def new_tenant(
    client: AsyncClient, rag_stack: VectorStore
) -> Callable[[], Awaitable[Caller]]:
    """Sign up a new tenant (its first user is an admin) with one seeded ready document."""

    async def make() -> Caller:
        signup = await client.post(
            "/v1/auth/signup",
            json={
                "tenant_name": f"tenant-{uuid.uuid4().hex}",
                "email": f"user-{uuid.uuid4().hex}@example.com",
                "password": "correct-horse-battery",
            },
        )
        assert signup.status_code == 201, signup.text
        user = signup.json()["user"]
        caller = Caller(
            headers={"Authorization": f"Bearer {signup.json()['access_token']}"},
            tenant_id=uuid.UUID(user["tenant_id"]),
            user_id=uuid.UUID(user["id"]),
            chunk_ids=[],
        )
        caller.chunk_ids = await _seed_document(client, rag_stack, caller)
        return caller

    return make


@pytest.fixture
def new_member(client: AsyncClient) -> Callable[[Caller], Awaitable[Caller]]:
    """Add a member user to an existing tenant and log them in."""

    async def make(owner: Caller) -> Caller:
        from app.core.security import hash_password
        from app.models.user import User, UserRole
        from app.repositories.session import session_scope

        email = f"member-{uuid.uuid4().hex}@example.com"
        async with session_scope() as session:
            user = User(
                tenant_id=owner.tenant_id,
                email=email,
                password_hash=hash_password("member-password-1"),
                role=UserRole.member,
            )
            session.add(user)
            await session.commit()
            user_id = user.id
        login = await client.post(
            "/v1/auth/login", json={"email": email, "password": "member-password-1"}
        )
        assert login.status_code == 200, login.text
        return Caller(
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            tenant_id=owner.tenant_id,
            user_id=user_id,
            chunk_ids=owner.chunk_ids,
        )

    return make


@pytest.fixture(autouse=True)
def _permissive_rate_limits(request: pytest.FixtureRequest) -> Iterator[None]:
    """Most tests aren't about rate limits; only tests marked real_rate_limit use Redis."""
    if request.node.get_closest_marker("real_rate_limit"):
        yield
        return
    from app.api.rate_limit import get_rate_limit_store
    from app.services.rate_limiting import Decision

    class _AllowAll:
        async def take(self, *args: object, **kwargs: object) -> Decision:
            return Decision(allowed=True, remaining=1.0, retry_after=0.0)

        async def refund(self, *args: object, **kwargs: object) -> None:
            # A 422 gives its tokens back (639b968); nothing was taken here.
            return None

    app.dependency_overrides[get_rate_limit_store] = lambda: _AllowAll()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_rate_limit_store, None)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_rate_limit: use the real Redis rate limiter, not the allow-all fake",
    )
    config.addinivalue_line(
        "markers", "integration: needs local services or cached models"
    )
