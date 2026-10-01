from functools import lru_cache

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings


@lru_cache
def _client() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=get_settings().qdrant_url)


async def ping() -> None:
    """Confirm the Qdrant service is reachable and responsive."""
    await _client().get_collections()
