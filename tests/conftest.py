import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from qdrant_client import QdrantClient

from app.core.config import get_settings
from app.main import app
from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder
from app.repositories.vector_store import VectorStore
from app.workers import tasks


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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: needs local services or cached models"
    )
