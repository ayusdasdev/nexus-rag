import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass

from app.core.redis import get_redis_client
from app.repositories import health as health_repo
from app.repositories import vector_store

_CHECK_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class DependencyStatus:
    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class ReadyResult:
    postgres: DependencyStatus
    redis: DependencyStatus
    qdrant: DependencyStatus

    @property
    def ready(self) -> bool:
        return self.postgres.ok and self.redis.ok and self.qdrant.ok


async def _check(coro: Awaitable[None]) -> DependencyStatus:
    try:
        await asyncio.wait_for(coro, timeout=_CHECK_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - any failure here means "not ready", by design
        return DependencyStatus(ok=False, detail=str(exc))
    return DependencyStatus(ok=True)


async def _ping_redis() -> None:
    await get_redis_client().ping()


class HealthService:
    async def check_ready(self) -> ReadyResult:
        postgres, redis_status, qdrant = await asyncio.gather(
            _check(health_repo.ping_db()),
            _check(_ping_redis()),
            _check(vector_store.ping()),
        )
        return ReadyResult(postgres=postgres, redis=redis_status, qdrant=qdrant)


def get_health_service() -> HealthService:
    return HealthService()
