import pytest
from pydantic import ValidationError

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


def test_conversation_settings_default_to_rule_rewrites_and_a_500_token_history() -> (
    None
):
    settings = Settings(_env_file=None)

    assert settings.rewrite_mode == "rule"
    assert settings.history_max_tokens == 500


def test_history_must_leave_room_for_sources_in_the_shared_budget() -> None:
    with pytest.raises(ValidationError, match="history_max_tokens"):
        Settings(_env_file=None, max_context_tokens=500, history_max_tokens=500)


# --- chunk sizes (M8 E4) -------------------------------------------------------------


def test_chunk_size_defaults_are_the_ones_every_ingest_so_far_used() -> None:
    from app.services.ingestion_pipeline import CHUNK_OVERLAP_TOKENS, MAX_CHUNK_TOKENS

    settings = Settings(_env_file=None)

    assert (settings.chunk_max_tokens, settings.chunk_overlap_tokens) == (350, 50)
    assert (MAX_CHUNK_TOKENS, CHUNK_OVERLAP_TOKENS) == (350, 50)


@pytest.mark.parametrize("size", [200, 500, 64])
def test_chunk_sizes_inside_the_bounds_are_accepted(size: int) -> None:
    assert Settings(chunk_max_tokens=size).chunk_max_tokens == size


@pytest.mark.parametrize(
    "fields",
    [
        {"chunk_max_tokens": 501},  # the cap stays under the embedder's 510 tokens
        {"chunk_max_tokens": 63},
        {"chunk_max_tokens": 200, "chunk_overlap_tokens": 200},
        {"chunk_max_tokens": 64, "chunk_overlap_tokens": 100},
        {"chunk_overlap_tokens": -1},
    ],
)
def test_chunk_sizes_outside_the_bounds_are_refused(fields: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Settings(**fields)  # type: ignore[arg-type]


def test_rrf_dense_weight_defaults_to_plain_rrf_and_is_bounded() -> None:
    assert Settings(_env_file=None).rrf_dense_weight == 1.0
    assert Settings(rrf_dense_weight=2.0).rrf_dense_weight == 2.0
    for bad in (0.0, -1.0, 10.5):
        with pytest.raises(ValidationError):
            Settings(rrf_dense_weight=bad)
