import pytest
from httpx import AsyncClient

from app.main import app
from app.services.health_service import (
    DependencyStatus,
    HealthService,
    ReadyResult,
    get_health_service,
)


class _FakeHealthService(HealthService):
    def __init__(self, result: ReadyResult) -> None:
        self._result = result

    async def check_ready(self) -> ReadyResult:
        return self._result


@pytest.mark.asyncio
async def test_health_returns_ok_without_checking_dependencies(
    client: AsyncClient,
) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_returns_200_when_all_dependencies_ok(client: AsyncClient) -> None:
    ok = DependencyStatus(ok=True)
    app.dependency_overrides[get_health_service] = lambda: _FakeHealthService(
        ReadyResult(postgres=ok, redis=ok, qdrant=ok)
    )

    response = await client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["postgres"] == {"ok": True, "detail": None}


@pytest.mark.asyncio
async def test_ready_returns_503_when_a_dependency_is_down(client: AsyncClient) -> None:
    ok = DependencyStatus(ok=True)
    down = DependencyStatus(ok=False, detail="connection refused")
    app.dependency_overrides[get_health_service] = lambda: _FakeHealthService(
        ReadyResult(postgres=ok, redis=down, qdrant=ok)
    )

    response = await client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["redis"] == {"ok": False, "detail": "connection refused"}
