import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    """A name to recognise the key by. The tenant comes from your token."""

    name: str = Field(min_length=1, max_length=100)

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": {"name": "Claude Code (MCP)"}}
    )


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str = Field(description="The key's first 12 characters, to recognise it.")
    scope: Literal["read"] = Field(
        description="read: search and read documents only; every other route is 403."
    )
    created_by: uuid.UUID
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(
        description="The key itself. Shown once: only its hash is stored, so it can't be "
        "shown again. Send it as `Authorization: Bearer <key>`."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "5d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e6",
                "name": "Claude Code (MCP)",
                "prefix": "nxk_Q2x5mN1p",
                "scope": "read",
                "created_by": "1b2c3d4e-5f60-4718-9a2b-3c4d5e6f7081",
                "created_at": "2026-10-12T09:00:00Z",
                "key": "nxk_Q2x5mN1p...(43 characters after nxk_)",
            }
        }
    )


class ApiKeyList(BaseModel):
    items: list[ApiKeyOut] = Field(description="Active keys, newest first.")
