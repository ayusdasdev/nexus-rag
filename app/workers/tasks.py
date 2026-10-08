from collections.abc import Iterator, Mapping, Sequence
from functools import lru_cache
from typing import Any
from uuid import UUID

from celery import Task
from celery.utils.log import get_task_logger

from app.core.config import get_settings
from app.core.errors import TransientError
from app.core.ids import chunk_id
from app.providers.embeddings import ModelNotCached, get_embedder, get_sparse_embedder
from app.providers.tokenizer import BgeTokenizer, TokenizerNotCached
from app.repositories import document_sync_repository as documents
from app.repositories.blob_store import get_blob_store
from app.repositories.document_sync_repository import ClaimedDocument
from app.repositories.vector_store import (
    VectorPoint,
    VectorStoreRejected,
    get_vector_store,
)
from app.services.ingestion_pipeline import ChunkStrategyUnavailable, chunk_document
from app.services.parsing import NoExtractableText, UnsupportedContentType
from app.workers.celery_app import PROCESS_DOCUMENT_TASK, celery_app

log = get_task_logger(__name__)

_MAX_ERROR_CHARS = 2000
EMBED_BATCH_SIZE = 32


class PermanentEmbedError(Exception):
    pass


# Celery ships no type information, so its Task base is Any here.
class ProcessDocumentTask(Task):  # type: ignore[misc]
    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        einfo: Any,
    ) -> None:
        # Runs once, when the task finally fails (retries exhausted or permanent).
        document_id = UUID(args[0])
        message = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]
        try:
            documents.mark_failed(document_id, message)
        except Exception:
            log.exception("could not record failure for document %s", document_id)


@celery_app.task(
    bind=True,
    base=ProcessDocumentTask,
    name=PROCESS_DOCUMENT_TASK,
    acks_late=True,
    autoretry_for=(TransientError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=900,
    time_limit=1200,
)  # type: ignore[untyped-decorator]
def process_document(self: Any, document_id: str) -> None:
    doc_id = UUID(document_id)
    claimed = documents.claim_for_processing(doc_id)
    if claimed is not None and not _chunk_stage(doc_id, claimed):
        return

    embed_claim = documents.claim_for_embedding(doc_id)
    if embed_claim is None:
        log.info("document %s is not in a processable state; skipping", doc_id)
        return
    _embed_stage(doc_id, embed_claim)


def _chunk_stage(doc_id: UUID, claimed: ClaimedDocument) -> bool:
    """Returns False when the document failed permanently."""
    path = get_blob_store().path_for(claimed.tenant_id, claimed.sha256)
    try:
        chunks = chunk_document(
            path, claimed.content_type, _tokenizer(), get_settings().chunk_strategy
        )
    except NoExtractableText:
        _fail(
            doc_id,
            "No extractable text: the file is scanned, image-only, or nearly empty.",
        )
        return False
    except UnsupportedContentType:
        _fail(doc_id, f"Unsupported file type: {claimed.content_type}")
        return False
    except ChunkStrategyUnavailable as exc:
        _fail(doc_id, f"Chunk strategy '{exc}' is not available yet.")
        return False
    except TokenizerNotCached:
        _fail(
            doc_id,
            "Tokenizer is not downloaded. Run `make fetch-models` and re-upload.",
        )
        return False
    except (TransientError, FileNotFoundError):
        raise
    except OSError as exc:
        raise TransientError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - any parser failure is a permanent, readable failure
        _fail(doc_id, f"Could not parse this file ({type(exc).__name__}).")
        return False

    documents.replace_chunks(
        doc_id,
        claimed.tenant_id,
        [
            documents.ChunkRow(
                id=chunk_id(doc_id, draft.chunk_index),
                chunk_index=draft.chunk_index,
                text=draft.text,
                heading_path=draft.heading_path,
                page=draft.page,
                token_count=draft.token_count,
            )
            for draft in chunks
        ],
    )
    return True


def _embed_stage(doc_id: UUID, claimed: ClaimedDocument) -> None:
    with_heading = get_settings().embed_with_heading
    try:
        chunks = documents.load_chunks_for_embedding(doc_id, claimed.tenant_id)
        store = get_vector_store()
        store.ensure_collection()
        dense_embedder = get_embedder()
        sparse_embedder = get_sparse_embedder()
        for batch in batched(chunks, EMBED_BATCH_SIZE):
            texts = [
                embedding_text(chunk.text, chunk.heading_path, with_heading)
                for chunk in batch
            ]
            dense = dense_embedder.embed_documents(texts)
            check_dense_dimension(dense, dense_embedder.dim)
            sparse = sparse_embedder.embed_documents(texts)
            store.upsert_points(
                [
                    VectorPoint(
                        chunk_id=chunk.id,
                        tenant_id=claimed.tenant_id,
                        document_id=doc_id,
                        chunk_index=chunk.chunk_index,
                        dense=vector,
                        sparse_indices=sparse_vector.indices,
                        sparse_values=sparse_vector.values,
                    )
                    for chunk, vector, sparse_vector in zip(
                        batch, dense, sparse, strict=True
                    )
                ]
            )
        store.delete_stale(claimed.tenant_id, doc_id, {chunk.id for chunk in chunks})
        documents.mark_ready(doc_id)
    except (ModelNotCached, PermanentEmbedError) as exc:
        _fail(doc_id, str(exc))
    except VectorStoreRejected as exc:
        _fail(doc_id, f"The vector store rejected the request ({exc}).")


def embedding_text(text: str, heading_path: str | None, with_heading: bool) -> str:
    if with_heading and heading_path:
        return f"{heading_path}\n{text}"
    return text


def batched[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def check_dense_dimension(vectors: Sequence[Sequence[float]], expected: int) -> None:
    for vector in vectors:
        if len(vector) != expected:
            raise PermanentEmbedError(
                f"Embedding dimension mismatch: expected {expected}, got {len(vector)}. "
                "The embedding model does not match the index."
            )


def _fail(document_id: UUID, message: str) -> None:
    # Readable, permanent: no retry. Errors reach documents.error via this path.
    documents.mark_failed(document_id, message[:_MAX_ERROR_CHARS])
    log.info("document %s failed: %s", document_id, message)


@lru_cache
def _tokenizer() -> BgeTokenizer:
    return BgeTokenizer()
