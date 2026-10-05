import asyncio
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path_for(self, tenant_id: UUID, sha256: str) -> Path:
        return self._root / str(tenant_id) / sha256

    async def save(self, tenant_id: UUID, sha256: str, data: bytes) -> Path:
        path = self.path_for(tenant_id, sha256)
        await asyncio.to_thread(_write, path, data)
        return path

    async def delete(self, tenant_id: UUID, sha256: str) -> None:
        await asyncio.to_thread(self.path_for(tenant_id, sha256).unlink, True)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@lru_cache
def _default_store() -> LocalBlobStore:
    return LocalBlobStore(Path(get_settings().upload_dir))


def get_blob_store() -> LocalBlobStore:
    return _default_store()
