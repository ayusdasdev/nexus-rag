import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Expand, RetrievalMode


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
        default=False,
        description="Include the retrieval trace in the response. Admins only; "
        "a non-admin gets 403.",
    )
    mode: RetrievalMode | None = Field(
        default=None,
        description="dense, sparse or hybrid (both, fused by RRF). Default: the "
        "RETRIEVAL_MODE setting.",
    )
    rerank: bool | None = Field(
        default=None,
        description="Rerank fused candidates with the cross-encoder. Default: the "
        "RERANK setting.",
    )
    candidates: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Results requested from each search before fusion. Default: the "
        "CANDIDATES setting.",
    )
    expand: Expand | None = Field(
        default=None,
        description="'neighbors' attaches the chunks just before and after each hit "
        "in its document. Default: the EXPAND setting.",
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "query": "How long does the battery last?",
                "document_ids": None,
                "limit": 10,
                "debug": False,
                "mode": "hybrid",
                "rerank": True,
                "candidates": 40,
                "expand": "none",
            }
        },
    )


class NeighborChunk(BaseModel):
    """A chunk adjacent to a hit in the same document, attached by expand=neighbors."""

    chunk_id: uuid.UUID
    chunk_index: int
    text: str


class SearchHit(BaseModel):
    """One ranked chunk."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    text: str
    heading_path: str | None = Field(default=None)
    page: int | None = Field(default=None)
    score: float
    neighbors: list[NeighborChunk] = Field(
        default_factory=list,
        description="Adjacent chunks in chunk_index order; empty unless expand=neighbors.",
    )

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
                "neighbors": [],
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
