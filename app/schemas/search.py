import uuid

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    """A search over the caller's own chunks. tenant_id always comes from the token."""

    query: str = Field(..., min_length=1, max_length=2000)
    document_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=100,
        description="Restrict the search to these documents (at most 100). An empty "
        "list matches nothing.",
    )
    limit: int = Field(default=10, ge=1, le=50)
    debug: bool = Field(
        default=False, description="Include the retrieval trace in the response."
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "query": "How long does the battery last?",
                "document_ids": None,
                "limit": 10,
                "debug": False,
            }
        },
    )


class SearchHit(BaseModel):
    """One ranked chunk."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    text: str
    heading_path: str | None = Field(default=None)
    page: int | None = Field(default=None)
    score: float

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "chunk_id": "0b6e2c1e-7d3a-5f4b-9a8c-1e2d3f4a5b6c",
                "document_id": "3f1c9a52-0d7e-4b8a-9c21-6e5f4a3b2c10",
                "chunk_index": 3,
                "text": "The battery lasts eight hours under normal use.",
                "heading_path": "Handbook > Specifications",
                "page": 2,
                "score": 7.42,
            }
        }
    )


class RankedItemResponse(BaseModel):
    """One entry of a Trace stage list: id, score and rank within that list."""

    chunk_id: uuid.UUID
    score: float
    rank: int
    source: str


class StageTimingResponse(BaseModel):
    name: str
    ms: float


class TraceResponse(BaseModel):
    """Per-stage timing and the ranked ids/scores from each stage. debug=true only."""

    stages: list[StageTimingResponse]
    dense: list[RankedItemResponse]
    sparse: list[RankedItemResponse]
    fused: list[RankedItemResponse]
    rerank: list[RankedItemResponse]


class SearchResponse(BaseModel):
    items: list[SearchHit]
    trace: TraceResponse | None = Field(
        default=None, description="Present only when the request set debug=true."
    )
