import uuid

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """A question answered from the caller's own ready documents. tenant_id comes from the
    token, never from here."""

    question: str = Field(..., min_length=1, max_length=2000)
    document_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=100,
        description="Answer only from these documents (at most 100). An empty list "
        "matches nothing, so the answer is a refusal.",
    )
    limit: int = Field(
        default=6,
        ge=1,
        le=20,
        description="Chunks retrieved before the context budget.",
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "question": "How long does charging take?",
                "document_ids": None,
                "limit": 6,
            }
        },
    )


# The payloads of the SSE events (ADR-0008). They document the stream in OpenAPI.


class ChatSource(BaseModel):
    number: int = Field(description="The N in [N] citations and <document id='N'>.")
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    heading_path: str | None
    text: str


class SourcesEvent(BaseModel):
    sources: list[ChatSource]


class TokenEvent(BaseModel):
    text: str


class ChatCitation(BaseModel):
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID


class CitationsEvent(BaseModel):
    citations: list[ChatCitation]
    dropped: list[int] = Field(
        description="Numbers the model cited that weren't sent; stripped from the answer."
    )


class DoneEvent(BaseModel):
    answer: str = Field(description="The final answer with invalid citations removed.")
    refused: bool
    external_links: list[str] = Field(
        description="URLs the answer contains. Reported only; never fetched or rendered."
    )
    skipped_chunks: int


class ErrorEvent(BaseModel):
    code: str
    message: str


SSE_EXAMPLE = (
    "event: sources\n"
    'data: {"sources": [{"number": 1, "chunk_id": "0b6e2c1e-7d3a-5f4b-9a8c-1e2d3f4a5b6c", '
    '"document_id": "3f1c9a52-0d7e-4b8a-9c21-6e5f4a3b2c10", "chunk_index": 0, '
    '"heading_path": "Guide > Charging", "text": "Charging takes two hours."}]}\n\n'
    "event: token\n"
    'data: {"text": "Two hours [1]."}\n\n'
    "event: citations\n"
    'data: {"citations": [{"number": 1, "chunk_id": "0b6e2c1e-7d3a-5f4b-9a8c-1e2d3f4a5b6c", '
    '"document_id": "3f1c9a52-0d7e-4b8a-9c21-6e5f4a3b2c10"}], "dropped": []}\n\n'
    "event: done\n"
    'data: {"answer": "Two hours [1].", "refused": false, "external_links": [], '
    '"skipped_chunks": 0}\n\n'
)
