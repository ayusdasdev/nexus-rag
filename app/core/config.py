from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "dev-insecure-secret-change-me-before-deploying"


class Settings(BaseSettings):
    """App configuration, loaded from the environment (and .env if present)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "local"
    log_level: str = "info"

    database_url: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    qdrant_url: str = "http://localhost:6333"

    max_upload_mb: int = 25
    # "parent_child" is reserved; selecting it fails the document with a clear message.
    chunk_strategy: Literal["structure", "parent_child"] = "structure"
    embedder: Literal["bge", "fake"] = "bge"
    fastembed_cache_dir: str = "data/fastembed_cache"
    embed_batch_size: int = 32
    # Prefix for query text only (BGE v1.5 retrieval instruction). Empty disables it.
    bge_query_instruction: str = ""
    # Prepend the chunk's heading_path to the text given to the embedder. Off by
    # default: unverified whether it helps retrieval for this corpus.
    embed_with_heading: bool = False
    upload_dir: str = "data/uploads"

    # Placeholder for /ready only (no real auth). Real tenant-scoped endpoints
    # use Depends(get_tenant_id) from app/api/deps.py, never a client header.
    tenant_header_name: str = "X-Tenant-Id"

    # Must be overridden via .env in any real deployment.
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    @model_validator(mode="after")
    def _forbid_default_jwt_secret_in_production(self) -> "Settings":
        if self.app_env == "production":
            if self.jwt_secret == _DEFAULT_JWT_SECRET:
                raise ValueError(
                    "jwt_secret is still the committed dev default - set JWT_SECRET "
                    "before running with app_env=production"
                )
            if len(self.jwt_secret) < 32:
                raise ValueError(
                    "jwt_secret must be at least 32 characters in production"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
