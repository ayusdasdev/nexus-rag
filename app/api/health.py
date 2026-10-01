from fastapi import APIRouter, Depends, Response, status

from app.schemas.health import DependencyStatusModel, HealthResponse, ReadyResponse
from app.services.health_service import HealthService, get_health_service

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
async def health() -> HealthResponse:
    """Return 200 as long as the process is up. Checks no dependencies."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse, summary="Readiness check")
async def ready(
    response: Response,
    service: HealthService = Depends(get_health_service),  # noqa: B008 - FastAPI DI pattern
) -> ReadyResponse:
    """Check Postgres, Redis and Qdrant connectivity (2s timeout each).

    Returns 200 with every dependency ok, or 503 with a per-dependency
    breakdown if any of them failed or timed out.
    """
    result = await service.check_ready()
    if not result.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        ready=result.ready,
        postgres=DependencyStatusModel(
            ok=result.postgres.ok, detail=result.postgres.detail
        ),
        redis=DependencyStatusModel(ok=result.redis.ok, detail=result.redis.detail),
        qdrant=DependencyStatusModel(ok=result.qdrant.ok, detail=result.qdrant.detail),
    )
