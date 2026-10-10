import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# bcrypt hashes at most 72 bytes and bcrypt 5 raises past that, so the limit is in bytes
# (a 30-character password of 3-byte characters is 90 bytes).
MAX_PASSWORD_BYTES = 72


def _at_most_72_bytes(password: str) -> str:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
    return password


# max_length (in characters) rejects huge bodies before the byte check runs.
Password = Annotated[
    str, Field(max_length=MAX_PASSWORD_BYTES), AfterValidator(_at_most_72_bytes)
]
Email = Annotated[str, Field(min_length=3, max_length=320)]


class SignupRequest(BaseModel):
    """Create a new tenant and its first (admin) user."""

    tenant_name: str = Field(..., min_length=1, max_length=255)
    email: Email
    password: Annotated[Password, Field(min_length=8)]

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "tenant_name": "Acme Corp",
                "email": "owner@acme.example",
                "password": "correct-horse-battery-staple",
            }
        },
    )


class LoginRequest(BaseModel):
    """Log in with email and password."""

    email: Email
    password: Password

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "owner@acme.example",
                "password": "correct-horse-battery-staple",
            }
        },
    )


class UserProfile(BaseModel):
    """A user's own profile - never includes password_hash."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: str
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "b3b1e6b0-6c2e-4f3a-8b1a-6a2e5b7e9f3a",
                "tenant_id": "a1c2e3d4-5f6a-4b7c-8d9e-0f1a2b3c4d5e",
                "email": "owner@acme.example",
                "role": "admin",
                "created_at": "2026-10-02T07:00:00Z",
            }
        }
    )


class TokenResponse(BaseModel):
    """Issued on successful signup or login."""

    access_token: str
    token_type: str = "bearer"
    user: UserProfile

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "user": {
                    "id": "b3b1e6b0-6c2e-4f3a-8b1a-6a2e5b7e9f3a",
                    "tenant_id": "a1c2e3d4-5f6a-4b7c-8d9e-0f1a2b3c4d5e",
                    "email": "owner@acme.example",
                    "role": "admin",
                    "created_at": "2026-10-02T07:00:00Z",
                },
            }
        }
    )
