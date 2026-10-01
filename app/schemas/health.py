from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Liveness response: the process is up and able to answer requests."""

    status: str = Field(
        default="ok", description="Always 'ok' if the process can respond."
    )

    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok"}})


class DependencyStatusModel(BaseModel):
    """Reachability of a single downstream dependency."""

    ok: bool = Field(description="Whether the dependency responded within the timeout.")
    detail: str | None = Field(
        default=None, description="Error message if ok is False."
    )

    model_config = ConfigDict(
        json_schema_extra={"example": {"ok": True, "detail": None}}
    )


class ReadyResponse(BaseModel):
    """Readiness response: a per-dependency breakdown plus an overall flag."""

    ready: bool = Field(description="True only if every dependency below is ok.")
    postgres: DependencyStatusModel
    redis: DependencyStatusModel
    qdrant: DependencyStatusModel

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ready": True,
                "postgres": {"ok": True, "detail": None},
                "redis": {"ok": True, "detail": None},
                "qdrant": {"ok": True, "detail": None},
            }
        }
    )
