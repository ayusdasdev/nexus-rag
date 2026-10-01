from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    tenant_header_name: str = "X-Tenant-Id"


@lru_cache
def get_settings() -> Settings:
    return Settings()
