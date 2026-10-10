"""POST /v1/chat (SSE): event order, headers, tenant isolation, refusal, 401, 422, 503.

Chunks and vectors are seeded straight into Postgres and a per-test Qdrant collection
with the fake embedders and reranker; the LLM is FakeLLM. No model downloads, no network.
"""

import asyncio
import json
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient, Response
from qdrant_client import QdrantClient

from app.api.chat import get_answer_slots, get_chat_llm
from app.api.documents import get_task_queue
from app.core.config import Settings, get_settings
from app.core.ids import chunk_id
from app.main import app
from app.models.chunk import Chunk
from app.models.document import DocumentStatus
from app.providers import embeddings
from app.providers import reranker as reranker_module
from app.providers.embeddings import FakeEmbedder, FakeSparseEmbedder
from app.providers.llm import FakeLLM
from app.repositories import document_repository
from app.repositories.blob_store import LocalBlobStore, get_blob_store
from app.repositories.session import session_scope
from app.repositories.vector_store import VectorPoint, VectorStore, get_vector_store
from app.services.chat import REFUSAL

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

CHAT_URL = "/v1/chat"
TEXTS = [
    "Charging the widget takes two hours from empty.",
    "Battery calibration: drain fully, then charge without interruption.",
    "Warranty claims need the original receipt.",
]
QUESTION = "How long does charging take?"


class _Queue:
    async def enqueue_ingest(self, document_id: uuid.UUID) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(
        embeddings, "get_settings", lambda: SimpleNamespace(embedder="fake")
    )
    monkeypatch.setattr(
        reranker_module, "get_settings", lambda: SimpleNamespace(embedder="fake")
    )
    embeddings.get_embedder.cache_clear()
    embeddings.get_sparse_embedder.cache_clear()
    reranker_module.get_reranker.cache_clear()
    try:
        yield
    finally:
        embeddings.get_embedder.cache_clear()
        embeddings.get_sparse_embedder.cache_clear()
        reranker_module.get_reranker.cache_clear()


@pytest.fixture
def store(tmp_path: Any) -> Iterator[VectorStore]:
    client = QdrantClient(url=get_settings().qdrant_url)
    name = f"test_{uuid.uuid4().hex}"
    vs = VectorStore(client, dim=FakeEmbedder.dim, collection=name)
    vs.ensure_collection()
    app.dependency_overrides[get_vector_store] = lambda: vs
    app.dependency_overrides[get_task_queue] = lambda: _Queue()
    app.dependency_overrides[get_blob_store] = lambda: LocalBlobStore(tmp_path)
    try:
        yield vs
    finally:
        for dependency in (get_vector_store, get_task_queue, get_blob_store):
            app.dependency_overrides.pop(dependency, None)
        if client.collection_exists(name):
            client.delete_collection(name)
        client.close()


@pytest.fixture
def llm() -> Iterator[FakeLLM]:
    fake = FakeLLM(["Charging takes ", "two hours [1][9]."])
    app.dependency_overrides[get_chat_llm] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_chat_llm, None)


async def _tenant(client: AsyncClient) -> dict[str, Any]:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "tenant_name": f"tenant-{uuid.uuid4().hex}",
            "email": f"user-{uuid.uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert signup.status_code == 201, signup.text
    return {
        "headers": {"Authorization": f"Bearer {signup.json()['access_token']}"},
        "tenant_id": uuid.UUID(signup.json()["user"]["tenant_id"]),
    }


async def _seed(
    client: AsyncClient, store: VectorStore, tenant: dict[str, Any]
) -> list[str]:
    upload = await client.post(
        "/v1/documents",
        headers=tenant["headers"],
        files={"file": ("widget.md", "\n\n".join(TEXTS).encode(), "text/markdown")},
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
                    tenant_id=tenant["tenant_id"],
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
                tenant_id=tenant["tenant_id"],
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


def _events(response: Response) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for frame in response.text.split("\n\n"):
        if not frame.strip():
            continue
        lines = dict(line.split(": ", 1) for line in frame.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_chat_streams_sources_tokens_citations_done_as_sse(
    client: AsyncClient, store: VectorStore, llm: FakeLLM
) -> None:
    tenant = await _tenant(client)
    ids = await _seed(client, store, tenant)

    response = await client.post(
        CHAT_URL, headers=tenant["headers"], json={"question": QUESTION}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = _events(response)
    assert [name for name, _ in events] == [
        "sources",
        "token",
        "token",
        "citations",
        "done",
    ]
    sources = events[0][1]["sources"]
    assert sources and {s["chunk_id"] for s in sources} <= set(ids)
    assert events[3][1]["dropped"] == [9]
    assert events[3][1]["citations"][0]["chunk_id"] == sources[0]["chunk_id"]
    assert events[4][1]["answer"] == "Charging takes two hours [1]."
    assert len(llm.calls) == 1


async def test_chat_sources_never_include_another_tenants_chunks(
    client: AsyncClient, store: VectorStore, llm: FakeLLM
) -> None:
    # Identical texts in one collection: a missing tenant filter would surface A's chunks.
    tenant_a = await _tenant(client)
    ids_a = await _seed(client, store, tenant_a)
    tenant_b = await _tenant(client)
    ids_b = await _seed(client, store, tenant_b)

    response = await client.post(
        CHAT_URL, headers=tenant_b["headers"], json={"question": QUESTION, "limit": 10}
    )

    sources = _events(response)[0][1]["sources"]
    returned = {s["chunk_id"] for s in sources}
    assert returned and returned <= set(ids_b)
    assert not returned & set(ids_a)
    # The documents section of the prompt holds exactly the sources sent, all B's.
    user_message = llm.calls[0][1].content
    assert user_message.count("<document id=") == len(sources)


async def test_chat_with_nothing_retrieved_refuses_without_calling_the_llm(
    client: AsyncClient, store: VectorStore, llm: FakeLLM
) -> None:
    tenant = await _tenant(client)

    response = await client.post(
        CHAT_URL, headers=tenant["headers"], json={"question": QUESTION}
    )

    assert response.status_code == 200
    events = _events(response)
    assert events[0] == ("sources", {"sources": []})
    assert events[-1][0] == "done"
    assert events[-1][1]["refused"] is True
    assert events[-1][1]["answer"] == REFUSAL
    assert llm.calls == []


async def test_chat_without_a_token_is_401(client: AsyncClient) -> None:
    response = await client.post(CHAT_URL, json={"question": QUESTION})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"question": ""},
        {"question": "x" * 2001},
        {"question": QUESTION, "limit": 0},
        {"question": QUESTION, "limit": 21},
        {"question": QUESTION, "tenant_id": str(uuid.uuid4())},
    ],
    ids=["missing", "empty", "too-long", "limit-0", "limit-21", "tenant-id"],
)
async def test_chat_with_an_invalid_body_is_422(
    client: AsyncClient, store: VectorStore, llm: FakeLLM, body: dict[str, Any]
) -> None:
    tenant = await _tenant(client)

    response = await client.post(CHAT_URL, headers=tenant["headers"], json=body)

    assert response.status_code == 422
    assert llm.calls == []


async def test_chat_with_no_llm_configured_is_503_before_streaming(
    client: AsyncClient, store: VectorStore
) -> None:
    tenant = await _tenant(client)
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct(
        **{
            **Settings().model_dump(),
            "llm_provider": "anthropic",
            "anthropic_api_key": None,
        }
    )
    try:
        response = await client.post(
            CHAT_URL, headers=tenant["headers"], json={"question": QUESTION}
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" not in response.text


async def test_chat_when_every_answer_slot_is_taken_streams_busy_without_an_llm_call(
    client: AsyncClient, store: VectorStore, llm: FakeLLM
) -> None:
    tenant = await _tenant(client)
    await _seed(client, store, tenant)
    full = asyncio.Semaphore(1)
    await full.acquire()
    app.dependency_overrides[get_answer_slots] = lambda: full
    try:
        response = await client.post(
            CHAT_URL, headers=tenant["headers"], json={"question": QUESTION}
        )
    finally:
        app.dependency_overrides.pop(get_answer_slots, None)

    assert response.status_code == 200
    assert _events(response) == [
        (
            "error",
            {
                "code": "llm_busy",
                "message": "The answer service is busy; retry shortly.",
            },
        )
    ]
    assert llm.calls == []


async def test_chat_restricted_to_another_tenants_document_refuses(
    client: AsyncClient, store: VectorStore, llm: FakeLLM
) -> None:
    tenant_a = await _tenant(client)
    await _seed(client, store, tenant_a)
    listing = await client.get("/v1/documents", headers=tenant_a["headers"])
    foreign_document = listing.json()["items"][0]["id"]
    tenant_b = await _tenant(client)
    await _seed(client, store, tenant_b)

    response = await client.post(
        CHAT_URL,
        headers=tenant_b["headers"],
        json={"question": QUESTION, "document_ids": [foreign_document]},
    )

    events = _events(response)
    assert events[0] == ("sources", {"sources": []})
    assert events[-1][1]["refused"] is True
    assert llm.calls == []
