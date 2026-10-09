from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.providers.anthropic_llm import AnthropicProvider
from app.providers.llm import LLMNotConfigured
from app.providers.llm_factory import build_llm
from app.providers.ollama_llm import OllamaProvider


@pytest.fixture(autouse=True)
def no_ambient_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's shell or .env must not decide these tests; _env_file=None below.
    for name in (
        "ANTHROPIC_API_KEY",
        "LLM_PROVIDER",
        "OLLAMA_MODEL",
        "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)


def test_the_default_provider_is_ollama_with_the_configured_model() -> None:
    llm = build_llm(_settings())

    assert isinstance(llm, OllamaProvider)
    assert llm.model == "llama3.2:3b"


def test_anthropic_is_built_only_with_an_api_key() -> None:
    llm = build_llm(
        _settings(llm_provider="anthropic", anthropic_api_key=SecretStr("sk-ant-x"))
    )

    assert isinstance(llm, AnthropicProvider)
    assert llm.model == "claude-opus-5-5"


def test_selecting_anthropic_without_a_key_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        _settings(llm_provider="anthropic")


def test_building_anthropic_without_a_key_never_returns_a_provider() -> None:
    # model_construct skips validation, as a misconfigured caller might.
    settings = Settings.model_construct(
        llm_provider="anthropic", anthropic_api_key=None
    )

    with pytest.raises(LLMNotConfigured):
        build_llm(settings)


def test_generation_defaults() -> None:
    settings = _settings()

    assert settings.max_context_tokens == 2500
    assert settings.answer_max_tokens == 512
    assert settings.anthropic_max_tokens == 16000
    assert settings.anthropic_effort == "medium"


def test_production_requires_an_https_anthropic_base_url() -> None:
    with pytest.raises(ValidationError, match="https"):
        _settings(
            app_env="production",
            jwt_secret="x" * 40,
            anthropic_base_url="http://api.anthropic.example",
        )


def test_answer_limits_default_and_are_bounded() -> None:
    settings = _settings()

    assert settings.chat_max_concurrent_answers == 4
    assert settings.llm_answer_deadline_seconds == 420.0
    with pytest.raises(ValidationError):
        _settings(chat_max_concurrent_answers=0)


def test_ollama_gets_its_own_300s_timeout_and_anthropic_keeps_120s() -> None:
    # 5.5: a cold CPU start (model load + ~90 s of prompt processing) outlasted 120 s.
    settings = _settings()
    assert settings.ollama_timeout_seconds == 300.0
    assert settings.llm_timeout_seconds == 120.0

    ollama = build_llm(settings)
    anthropic = build_llm(
        _settings(llm_provider="anthropic", anthropic_api_key=SecretStr("sk-ant-x"))
    )

    assert isinstance(ollama, OllamaProvider) and ollama.timeout == 300.0
    assert isinstance(anthropic, AnthropicProvider) and anthropic.timeout == 120.0


def test_the_answer_deadline_outlasts_the_ollama_timeout() -> None:
    settings = _settings()

    assert settings.llm_answer_deadline_seconds > settings.ollama_timeout_seconds
