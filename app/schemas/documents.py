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
