"""In-process wiring from the runner to the app's real retrieval (M8).

The runner calls app.services.retrieval.retrieve() directly - the code path behind
/v1/search - instead of going over HTTP, where the search rate limit (20, then 1/5 s)
would pace a run. Every call is scoped to the eval tenant recorded by
eval/tools/ingest_corpus.py; Qdrant is still reached only through VectorStore, which
applies the tenant filter. Reranker scores go through the disk cache.
"""

import json
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.providers.llm import LLMProvider
from app.services.chat import answer_events
from app.services.retrieval import RetrievedChunk, RetrieveResult
from eval.runner import Hit, RunConfig, SearchFn, SearchResult

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "eval" / "state" / "eval_tenant.json"
RERANK_CACHE = ROOT / "eval" / "state" / "rerank_cache.sqlite"

RetrieveFn = Callable[..., Awaitable[RetrieveResult]]
AnswerFn = Callable[
    [str, Sequence[RetrievedChunk]], Coroutine[Any, Any, dict[str, Any]]
]


def make_answerer(llm: LLMProvider, settings: Settings) -> AnswerFn:
    """The app's real answer pipeline (answer_events), captured event by event.

    Eval generation is Ollama only: anything else is refused, so a run can't reach a paid
    provider through a setting in .env."""
    if settings.llm_provider != "ollama":
        raise SystemExit(
            f"eval generation runs on ollama only; LLM_PROVIDER is {settings.llm_provider!r}"
        )

    async def answer(question: str, items: Sequence[RetrievedChunk]) -> dict[str, Any]:
        started = time.perf_counter()
        out: dict[str, Any] = {
            "text": None,
            "raw_text": "",
            "cited": [],
            "dropped": [],
            "refused": None,
            "sources": [],
            "external_links": [],
            "error": None,
            "first_token_ms": None,
        }
        tokens: list[str] = []
        async for event in answer_events(
            question,
            items,
            llm,
            max_context_tokens=settings.max_context_tokens,
            answer_max_tokens=settings.answer_max_tokens,
            deadline_seconds=settings.llm_answer_deadline_seconds,
        ):
            if event.event == "sources":
                out["sources"] = [s["text"] for s in event.data["sources"]]
            elif event.event == "token":
                if out["first_token_ms"] is None:
                    out["first_token_ms"] = (time.perf_counter() - started) * 1000
                tokens.append(event.data["text"])
            elif event.event == "citations":
                out["cited"] = [c["number"] for c in event.data["citations"]]
                out["dropped"] = list(event.data["dropped"])
            elif event.event == "done":
                out["text"] = event.data["answer"]
                out["refused"] = event.data["refused"]
                out["external_links"] = event.data["external_links"]
            elif event.event == "error":
                out["error"] = event.data["code"]
        out["raw_text"] = "".join(tokens)
        out["generate_ms"] = (time.perf_counter() - started) * 1000
        return out

    return answer


def build_search(
    retrieve_fn: RetrieveFn,
    tenant_id: UUID,
    doc_names: Mapping[UUID, str],
    answer_fn: AnswerFn | None = None,
) -> SearchFn:
    async def search(question: dict[str, Any], config: RunConfig) -> SearchResult:
        result = await retrieve_fn(
            tenant_id=tenant_id,
            query=question["question"],
            limit=config.limit,
            candidates=config.candidates,
            use_dense=config.mode in ("dense", "hybrid"),
            use_sparse=config.mode in ("sparse", "hybrid"),
            use_rerank=config.rerank,
            expand=config.expand,
            trace=True,
        )
        hits = [
            Hit(
                chunk_id=str(item.chunk_id),
                document=doc_names.get(item.document_id, str(item.document_id)),
                chunk_index=item.chunk_index,
                text=item.text,
                score=item.score,
            )
            for item in result.items
        ]
        stages = {s.name: s.ms for s in result.trace.stages} if result.trace else {}
        answer = None
        if answer_fn is not None:
            answer = await answer_fn(question["question"], result.items)
            stages["generate"] = answer["generate_ms"]
        return SearchResult(hits=hits, stages_ms=stages, answer=answer)

    return search


def answer_fn_for(
    generate: bool, settings: Settings, build: Callable[[Settings], LLMProvider]
) -> AnswerFn | None:
    """None for a retrieval-only run. Otherwise the answerer, after the Ollama-only check,
    so a non-Ollama provider is never built."""
    if not generate:
        return None
    if settings.llm_provider != "ollama":
        raise SystemExit(
            f"eval generation runs on ollama only; LLM_PROVIDER is {settings.llm_provider!r}"
        )
    return make_answerer(build(settings), settings)


def make_search(generate: bool) -> tuple[SearchFn, Callable[[], Awaitable[None]]]:
    """The real search for the eval tenant. Models load on first use, not at import."""
    from functools import partial

    from app.core.config import get_settings
    from app.providers.llm_factory import build_llm
    from app.providers.reranker import get_reranker
    from app.repositories import chunk_repository
    from app.repositories.session import dispose_engine
    from app.repositories.vector_store import get_vector_store
    from app.services.retrieval import retrieve
    from eval.rerank_cache import CachingReranker

    answer_fn = answer_fn_for(generate, get_settings(), build_llm)
    state = json.loads(STATE.read_text())
    doc_names = {UUID(d["id"]): d["file"] for d in state["documents"]}
    retrieve_fn = partial(
        retrieve,
        store=get_vector_store(),
        reranker=CachingReranker(get_reranker(), RERANK_CACHE),
        fetch_chunks=chunk_repository.fetch_chunks,
        fetch_neighbors=chunk_repository.fetch_neighbors,
    )
    search = build_search(retrieve_fn, UUID(state["tenant_id"]), doc_names, answer_fn)
    return search, dispose_engine
