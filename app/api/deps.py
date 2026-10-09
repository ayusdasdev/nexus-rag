from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import InvalidToken, decode_access_token
from app.repositories.auth_repository import get_user_by_id

_bearer_scheme = HTTPBearer(auto_error=False)


def _credentials_error() -> HTTPException:
    # A fresh instance per raise: a shared one grows its traceback on every bad token.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    tenant_id: UUID
    email: str
    role: str
    created_at: datetime


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(  # noqa: B008
        _bearer_scheme
    ),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token_payload = decode_access_token(credentials.credentials)
    except InvalidToken:
        raise _credentials_error() from None

    user = await get_user_by_id(token_payload.tenant_id, token_payload.user_id)
    if user is None:
        raise _credentials_error()

    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
    )


def get_tenant_id(
    current_user: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> UUID:
    return current_user.tenant_id
