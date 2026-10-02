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
