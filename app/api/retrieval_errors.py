from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status

from app.core.errors import TransientError
from app.providers.embeddings import ModelNotCached
from app.repositories.vector_store import VectorStoreRejected


@contextmanager
def retrieval_errors() -> Iterator[None]:
    """Map retrieval failures to HTTP errors with fixed, internals-free messages.

    Shared by /v1/search and /v1/chat (where retrieval runs before the stream opens).
    """
    try:
        yield
    except TransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store is temporarily unavailable; retry the search",
        ) from exc
    except ModelNotCached as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The search service is not fully configured; try again later",
        ) from exc
    except VectorStoreRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed due to an internal error",
        ) from exc
