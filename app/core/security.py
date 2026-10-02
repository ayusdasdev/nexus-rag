import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class TokenPayload:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# A fixed, valid bcrypt hash with no matching real account - used so a login
# for an unknown email still pays bcrypt's cost, instead of short-circuiting
# straight to a fast rejection that would make "unknown email" distinguishable
# from "wrong password" by timing alone.
DUMMY_HASH = hash_password("dummy-password-for-timing-equalization")


def create_access_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.jwt_expire_minutes)
    )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role,
        "iat": now,
        "exp": now + delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenPayload:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.InvalidTokenError as exc:
        raise InvalidToken(str(exc)) from exc

    try:
        return TokenPayload(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            role=payload["role"],
        )
    except (KeyError, ValueError) as exc:
        raise InvalidToken("malformed token payload") from exc
