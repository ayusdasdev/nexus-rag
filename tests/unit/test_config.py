import pytest

from app.core.config import Settings


def test_production_rejects_default_jwt_secret() -> None:
    """Regression test: booting with app_env=production and the committed
    dev-default secret must fail fast, not silently sign tokens with a
    secret anyone with repo access already knows."""
    with pytest.raises(ValueError, match="committed dev default"):
        Settings(
            app_env="production",
            jwt_secret="dev-insecure-secret-change-me-before-deploying",
        )


def test_production_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(app_env="production", jwt_secret="too-short")


def test_production_accepts_strong_jwt_secret() -> None:
    settings = Settings(app_env="production", jwt_secret="a" * 40)
    assert settings.jwt_secret == "a" * 40


def test_local_env_allows_default_jwt_secret() -> None:
    settings = Settings(app_env="local")
    assert settings.jwt_secret


def test_settings_offer_no_client_supplied_tenant_header() -> None:
    """tenant_id comes only from the token (CLAUDE.md); a configurable tenant header
    would invite reading it from the request instead."""
    assert not any("tenant" in name for name in Settings.model_fields)


def test_retrieval_switch_defaults() -> None:
    settings = Settings()

    assert settings.retrieval_mode == "hybrid"
    assert settings.rerank is True
    assert settings.candidates == 40
    assert settings.expand == "none"


def test_retrieval_mode_rejects_an_unknown_value() -> None:
    with pytest.raises(ValueError, match="retrieval_mode"):
        Settings(retrieval_mode="keyword")
