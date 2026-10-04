from functools import lru_cache

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
