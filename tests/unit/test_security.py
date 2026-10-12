import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.security import InvalidToken, decode_access_token


def _token(iat: datetime, exp: datetime) -> str:
    settings = get_settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()),
        "role": "admin",
        "iat": iat,
        "exp": exp,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_a_token_issued_2s_in_the_future_is_accepted() -> None:
    # The wall clock can step backwards (WSL steps about 1.4 s every ~30 s), so a token
    # can be checked "before" it was issued. That must not be a 401.
    now = datetime.now(UTC)
    token = _token(iat=now + timedelta(seconds=2), exp=now + timedelta(minutes=5))

    payload = decode_access_token(token)

    assert payload.role == "admin"


def test_a_token_expired_by_10s_is_still_rejected() -> None:
    # Leeway (5 s by default) must not keep an expired token alive past that margin.
    now = datetime.now(UTC)
    token = _token(iat=now - timedelta(minutes=5), exp=now - timedelta(seconds=10))

    with pytest.raises(InvalidToken, match="expired"):
        decode_access_token(token)


def test_a_token_issued_30s_in_the_future_is_rejected() -> None:
    now = datetime.now(UTC)
    token = _token(iat=now + timedelta(seconds=30), exp=now + timedelta(minutes=5))

    with pytest.raises(InvalidToken, match="not yet valid"):
        decode_access_token(token)


def test_jwt_leeway_defaults_to_5s_and_is_bounded() -> None:
    assert Settings().jwt_leeway_seconds == 5
    with pytest.raises(ValidationError):
        Settings(jwt_leeway_seconds=-1)
    with pytest.raises(ValidationError):
        Settings(jwt_leeway_seconds=61)


# --- API keys (M9 9.2) -----------------------------------------------------------------


def test_a_new_api_key_is_random_prefixed_and_only_its_hash_is_kept() -> None:
    import re

    from app.core.security import hash_api_key, new_api_key

    key, digest = new_api_key()
    other, _ = new_api_key()

    assert re.fullmatch(r"nxk_[A-Za-z0-9_-]{43}", key)
    assert key != other
    assert digest == hash_api_key(key) and len(digest) == 64
    assert key not in digest


def test_only_strings_shaped_like_our_keys_count_as_api_keys() -> None:
    from app.core.security import looks_like_api_key, new_api_key

    assert looks_like_api_key(new_api_key()[0])
    assert not looks_like_api_key("eyJhbGciOiJIUzI1NiJ9.e30.x")
    assert not looks_like_api_key("nxk_short")
