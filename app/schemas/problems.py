from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Problem(BaseModel):
    """RFC 9457 problem details: the body of every 4xx/5xx from this API."""

    type: str = Field(description='Always "about:blank": the status code says it all.')
    title: str = Field(description="The HTTP status phrase.")
    status: int
    detail: str = Field(description="What went wrong, for a human. No internals.")
    request_id: str | None = Field(
        description="Echo of X-Request-ID; quote it when reporting a problem."
    )
    errors: list[dict[str, Any]] | None = Field(
        default=None, description="422 only: each invalid field (loc, msg, type)."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": "Conversation not found",
                "request_id": "3f9c2b1e8a7d4c6e9f0a1b2c3d4e5f60",
            }
        }
    )
