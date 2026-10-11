import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackRequest(BaseModel):
    """Thumbs up (1) or down (-1) on one of your own answers."""

    value: Literal[-1, 1]

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": {"value": -1}}
    )


class TraceOut(BaseModel):
    """One answer, reconstructed: what was asked, how it was retrieved, what came back.
    Stages hold chunk ids, scores and ranks only, never document text."""

    request_id: str
    endpoint: Literal["chat", "conversation"]
    user_id: uuid.UUID
    message_id: uuid.UUID | None = Field(
        description="The assistant message, for conversation turns."
    )
    query: str
    rewritten_query: str | None
    stages: dict[str, Any] = Field(
        description="Per retrieval stage (dense, sparse, fused, rerank; top 20) and the "
        "final items: chunk_id, score, rank."
    )
    latency_ms: dict[str, float] = Field(description="Milliseconds per traced stage.")
    prompt_tokens: int | None = Field(description="Estimated (characters / 4).")
    completion_tokens: int | None = Field(description="Estimated (characters / 4).")
    model: str | None
    answer: str | None
    error: str | None = Field(description="Error code if the answer failed.")
    est_cost: Decimal | None = Field(description="Null on the free local stack.")
    feedback: Literal[-1, 1] | None
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "request_id": "3f2b1c0d9e8f7a6b5c4d3e2f1a0b9c8d",
                "endpoint": "chat",
                "user_id": "1b2c3d4e-5f60-4718-9a2b-3c4d5e6f7081",
                "message_id": None,
                "query": "How long does charging take?",
                "rewritten_query": None,
                "stages": {
                    "final": [
                        {
                            "chunk_id": "0b6e2c1e-7d3a-5f4b-9a8c-1e2d3f4a5b6c",
                            "document_id": "3f1c9a52-0d7e-4b8a-9c21-6e5f4a3b2c10",
                            "score": 0.91,
                            "rank": 1,
                        }
                    ]
                },
                "latency_ms": {
                    "embed_query": 12.0,
                    "rerank": 37000.0,
                    "generate": 118000.0,
                },
                "prompt_tokens": 1450,
                "completion_tokens": 22,
                "model": "llama3.2:3b",
                "answer": "Two hours [1].",
                "error": None,
                "est_cost": None,
                "feedback": None,
                "created_at": "2026-10-11T12:00:00Z",
            }
        }
    )
