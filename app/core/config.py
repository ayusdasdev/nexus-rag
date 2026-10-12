from functools import lru_cache
from typing import Literal

from pydantic import Field, IPvAnyNetwork, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "dev-insecure-secret-change-me-before-deploying"

RetrievalMode = Literal["dense", "sparse", "hybrid"]
# "parent" joins when parent_child chunking exists; until then it is not accepted.
Expand = Literal["none", "neighbors"]
LLMProviderName = Literal["ollama", "anthropic"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
RewriteMode = Literal["rule", "llm", "off"]
# How answers are written (M10): "cite" (rag_system) or "quote_then_cite" (rag_system_quote).
AnswerStyle = Literal["cite", "quote_then_cite"]


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
    # Chunk size and overlap in embedder tokens (M8 E4 sweep). 500 is the cap: a chunk plus
    # the special tokens must stay under BGE's 512-token input (510 usable).
    chunk_max_tokens: int = Field(default=350, ge=64, le=500)
    chunk_overlap_tokens: int = Field(default=50, ge=0)
    # Query traces hold users' questions and answers: kept this long (M9, your choice).
    trace_retention_days: int = Field(default=30, ge=1, le=365)
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
    # Weighted RRF (M10): the dense list's weight against BM25's 1.0. 1.0 is plain RRF.
    rrf_dense_weight: float = Field(default=1.0, gt=0, le=10)
    # The answer prompt (M10). "cite" is the M5 prompt; "quote_then_cite" quotes the
    # answering sentence first (failure analysis, bucket E).
    answer_style: AnswerStyle = "cite"
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
    # A cold CPU start (model load + ~90 s of prompt processing at ~15 tokens/s) outlasted
    # 120 s in M5 5.5; see docs/decisions/generation-observations.md.
    ollama_timeout_seconds: float = Field(default=300.0, gt=0)
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
    # Conversations (ADR-0009): history shares max_context_tokens, capped at this.
    history_max_tokens: int = Field(default=500, ge=0)
    rewrite_mode: RewriteMode = "rule"
    # Bounds on stored conversation data (M6 review, MEDIUM-3); past them, 409.
    conversation_max_messages: int = Field(default=1000, ge=2)
    max_conversations_per_user: int = Field(default=1000, ge=1)
    # Per-tenant token buckets (M7); each user gets half. Chat covers /v1/chat and
    # conversation messages, search covers /v1/search, default every other authed route.
    rate_limit_enabled: bool = True
    rate_limit_chat_capacity: float = Field(default=5, gt=0)
    rate_limit_chat_refill_per_second: float = Field(default=1 / 60, ge=0)
    rate_limit_search_capacity: float = Field(default=20, gt=0)
    rate_limit_search_refill_per_second: float = Field(default=0.2, ge=0)
    rate_limit_default_capacity: float = Field(default=120, gt=0)
    rate_limit_default_refill_per_second: float = Field(default=2.0, ge=0)
    # Uploads cost worker time (parse, chunk, embed), so they get their own bucket.
    rate_limit_upload_capacity: float = Field(default=10, gt=0)
    rate_limit_upload_refill_per_second: float = Field(default=1 / 60, ge=0)
    # Unauthenticated routes (M7 review, HIGH-1): per client IP, per login email, and a
    # global signup budget. X-Forwarded-For counts only from these proxies (CIDRs).
    trusted_proxies: list[IPvAnyNetwork] = Field(default_factory=list)
    rate_limit_signup_ip_capacity: float = Field(default=3, gt=0)
    rate_limit_signup_ip_refill_per_second: float = Field(default=3 / 3600, ge=0)
    rate_limit_signup_global_capacity: float = Field(default=30, gt=0)
    rate_limit_signup_global_refill_per_second: float = Field(default=30 / 3600, ge=0)
    rate_limit_login_ip_capacity: float = Field(default=20, gt=0)
    rate_limit_login_ip_refill_per_second: float = Field(default=0.1, ge=0)
    rate_limit_login_email_capacity: float = Field(default=5, gt=0)
    rate_limit_login_email_refill_per_second: float = Field(default=1 / 60, ge=0)
    llm_answer_deadline_seconds: float = Field(default=420.0, gt=0)

    @model_validator(mode="after")
    def _overlap_below_chunk_size(self) -> "Settings":
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError(
                "chunk_overlap_tokens must be smaller than chunk_max_tokens"
            )
        return self

    @model_validator(mode="after")
    def _history_leaves_room_for_sources(self) -> "Settings":
        if self.history_max_tokens >= self.max_context_tokens:
            raise ValueError("history_max_tokens must be below max_context_tokens")
        return self

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
