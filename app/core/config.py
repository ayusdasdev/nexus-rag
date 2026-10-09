from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "dev-insecure-secret-change-me-before-deploying"

RetrievalMode = Literal["dense", "sparse", "hybrid"]
# "parent" joins when parent_child chunking exists; until then it is not accepted.
Expand = Literal["none", "neighbors"]
LLMProviderName = Literal["ollama", "anthropic"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


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

    # Retrieval defaults; POST /v1/search may override each per request.
    retrieval_mode: RetrievalMode = "hybrid"
    rerank: bool = True
    # Results requested from each of the dense and sparse searches.
    candidates: int = Field(default=40, ge=1, le=100)
    expand: Expand = "none"

    # Must be overridden via .env in any real deployment.
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    # Clock-skew tolerance for iat and exp. It also lets a token live up to this long
    # past exp, so keep it small (ADR-0006).
    jwt_leeway_seconds: int = Field(default=5, ge=0, le=60)

    # Generation (M5). Ollama is the default; Anthropic needs ANTHROPIC_API_KEY.
    llm_provider: LLMProviderName = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_num_ctx: int = Field(default=4096, ge=512)
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_effort: Effort = "medium"
    # Thinking counts toward max_tokens on the default model, so requests ask for at least this.
    anthropic_max_tokens: int = Field(default=16000, ge=1024)
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    # Budget for retrieved text in the prompt, and for the answer itself.
    max_context_tokens: int = Field(default=2500, ge=100)
    answer_max_tokens: int = Field(default=512, ge=16)
    # Per-process cap on LLM answers in flight, and a deadline for a whole answer. A
    # per-tenant quota comes with the M7 rate limiter.
    chat_max_concurrent_answers: int = Field(default=4, ge=1, le=64)
    llm_answer_deadline_seconds: float = Field(default=180.0, gt=0)

    @model_validator(mode="after")
    def _anthropic_needs_a_key(self) -> "Settings":
        if self.llm_provider == "anthropic" and (
            self.anthropic_api_key is None
            or not self.anthropic_api_key.get_secret_value()
        ):
            raise ValueError("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY to be set")
        return self

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
            if not self.anthropic_base_url.startswith("https://"):
                # The API key travels in a header; never send it in cleartext.
                raise ValueError("anthropic_base_url must be https in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
