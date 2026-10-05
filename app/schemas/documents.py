import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    """A document uploaded by the caller's tenant."""

    id: uuid.UUID = Field(description="Document id.")
    filename: str = Field(
        description="Display name, sanitised. Never used for storage."
    )
    content_type: str = Field(description="Type detected from the file's content.")
    size_bytes: int = Field(description="Size of the uploaded file in bytes.")
    sha256: str = Field(description="Hex SHA-256 of the file bytes.")
    status: str = Field(description="Processing status, e.g. 'uploaded'.")
    error: str | None = Field(
        default=None, description="Failure reason when status is 'failed'."
    )
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "3f1c9a52-0d7e-4b8a-9c21-6e5f4a3b2c10",
                "filename": "handbook.pdf",
                "content_type": "application/pdf",
                "size_bytes": 482193,
                "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                "status": "uploaded",
                "error": None,
                "created_at": "2026-10-04T12:00:00Z",
            }
        }
    )


class DocumentPage(BaseModel):
    """One page of the caller's documents, newest first."""

    items: list[DocumentResponse]
    total: int = Field(description="Total documents in the tenant.")
    limit: int
    offset: int


class ChunkResponse(BaseModel):
    """A chunk produced from a document."""

    id: uuid.UUID = Field(
        description="Deterministic: uuid5 of document id and chunk index."
    )
    chunk_index: int
    text: str
    heading_path: str | None = Field(
        default=None, description="Ancestor headings, e.g. 'A > B'."
    )
    page: int | None = Field(default=None, description="Source page when known.")
    token_count: int = Field(description="Content tokens, excluding [CLS]/[SEP].")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "0b6e2c1e-7d3a-5f4b-9a8c-1e2d3f4a5b6c",
                "chunk_index": 0,
                "text": "Install the tools before you start.",
                "heading_path": "Handbook > Setup",
                "page": None,
                "token_count": 7,
            }
        }
    )


class ChunkPage(BaseModel):
    items: list[ChunkResponse]
    total: int
    limit: int
    offset: int
