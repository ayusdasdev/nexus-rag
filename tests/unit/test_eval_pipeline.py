"""eval/pipeline.build_search: a RunConfig maps onto retrieve()'s arguments, and hits come
back with their document's file name and per-stage timings (M8)."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.services.retrieval import RetrievedChunk, RetrieveResult, StageTiming, Trace
from eval.pipeline import build_search
from eval.runner import Mode, RunConfig

TENANT = uuid4()
DOC = uuid4()


def _fake_retrieve(seen: list[dict[str, Any]]) -> Any:
    async def retrieve(**kwargs: Any) -> RetrieveResult:
        seen.append(kwargs)
        item = RetrievedChunk(
            chunk_id=UUID(int=1),
            document_id=DOC,
            chunk_index=3,
            text="t",
            heading_path=None,
            page=None,
            score=0.5,
            rank=1,
        )
        trace = Trace(
            stages=[StageTiming("embed_query", 2.0), StageTiming("rerank", 9.0)],
            dense=[],
            sparse=[],
            fused=[],
            rerank=[],
        )
        return RetrieveResult(items=[item], trace=trace)

    return retrieve


@pytest.mark.parametrize(
    "mode,dense,sparse",
    [("dense", True, False), ("sparse", False, True), ("hybrid", True, True)],
)
def test_config_maps_onto_retrieve(mode: Mode, dense: bool, sparse: bool) -> None:
    seen: list[dict[str, Any]] = []
    search = build_search(_fake_retrieve(seen), TENANT, {DOC: "a.md"})
    config = RunConfig(
        mode=mode, rerank=False, candidates=20, expand="neighbors", limit=5
    )

    asyncio.run(search({"id": "q1", "question": "Q?"}, config))

    call = seen[0]
    assert (call["use_dense"], call["use_sparse"]) == (dense, sparse)
    assert (call["use_rerank"], call["candidates"], call["expand"], call["limit"]) == (
        False,
        20,
        "neighbors",
        5,
    )
    assert (
        call["tenant_id"] == TENANT and call["query"] == "Q?" and call["trace"] is True
    )


def test_hits_carry_the_file_name_and_stage_timings() -> None:
    search = build_search(_fake_retrieve([]), TENANT, {DOC: "a.md"})

    result = asyncio.run(search({"id": "q1", "question": "Q?"}, RunConfig()))

    hit = result.hits[0]
    assert (hit.document, hit.chunk_index, hit.text, hit.score) == ("a.md", 3, "t", 0.5)
    assert hit.chunk_id == str(UUID(int=1))
    assert result.stages_ms == {"embed_query": 2.0, "rerank": 9.0}


def test_with_neighbors_the_scored_text_is_what_the_answer_model_would_see() -> None:
    from app.repositories.chunk_repository import ChunkRecord

    def record(index: int, text: str) -> ChunkRecord:
        return ChunkRecord(
            id=uuid4(),
            document_id=DOC,
            chunk_index=index,
            text=text,
            heading_path=None,
            page=None,
            token_count=1,
        )

    async def retrieve(**kwargs: Any) -> RetrieveResult:
        assert kwargs["expand"] == "neighbors"
        item = RetrievedChunk(
            chunk_id=UUID(int=1),
            document_id=DOC,
            chunk_index=3,
            text="hit",
            heading_path=None,
            page=None,
            score=0.5,
            rank=1,
            neighbors=(record(2, "before"), record(4, "after")),
        )
        return RetrieveResult(items=[item], trace=None)

    search = build_search(retrieve, TENANT, {DOC: "a.md"})
    result = asyncio.run(
        search({"id": "q1", "question": "Q?"}, RunConfig(expand="neighbors"))
    )

    hit = result.hits[0]
    assert hit.text == "before\n\nhit\n\nafter"
    assert hit.neighbor_indexes == [2, 4]


def test_without_neighbors_a_hit_records_none() -> None:
    result = asyncio.run(
        build_search(_fake_retrieve([]), TENANT, {DOC: "a.md"})(
            {"id": "q1", "question": "Q?"}, RunConfig()
        )
    )

    assert result.hits[0].neighbor_indexes == []


def test_the_dense_weight_reaches_retrieve_and_defaults_to_plain_rrf() -> None:
    seen: list[dict[str, Any]] = []
    search = build_search(_fake_retrieve(seen), TENANT, {DOC: "a.md"})

    asyncio.run(search({"id": "q1", "question": "Q?"}, RunConfig()))
    asyncio.run(search({"id": "q1", "question": "Q?"}, RunConfig(dense_weight=2.0)))

    assert [call["dense_weight"] for call in seen] == [1.0, 2.0]
