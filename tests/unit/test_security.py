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
