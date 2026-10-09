from app.core.config import Settings, get_settings
from app.providers.anthropic_llm import AnthropicProvider
from app.providers.llm import LLMNotConfigured, LLMProvider
from app.providers.ollama_llm import OllamaProvider


def build_llm(settings: Settings) -> LLMProvider:
    """The configured provider. Anthropic is never built without an API key."""
    if settings.llm_provider == "anthropic":
        key = settings.anthropic_api_key
        if key is None or not key.get_secret_value():
            raise LLMNotConfigured("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        return AnthropicProvider(
            api_key=key.get_secret_value(),
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            effort=settings.anthropic_effort,
            min_max_tokens=settings.anthropic_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
    return OllamaProvider(
        base_url=settings.ollama_url,
        model=settings.ollama_model,
        num_ctx=settings.ollama_num_ctx,
        timeout=settings.llm_timeout_seconds,
    )


def get_llm() -> LLMProvider:
    """FastAPI dependency; tests override it with FakeLLM."""
    return build_llm(get_settings())
