from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.request_context import set_tenant_id
from app.core.security import (
    InvalidToken,
    decode_access_token,
    hash_api_key,
    looks_like_api_key,
)
from app.models.user import UserRole
from app.repositories import api_key_repository
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
    # "full" for a login token; "read" for an API key (M9 9.2), whose user is its creator.
    scope: str = "full"
    api_key_id: UUID | None = None


# The only operations an API key may call (M9 9.2): reads the MCP server needs, as (HTTP
# method, endpoint function name). Names are unique app-wide (they are the OpenAPI
# operation ids), unlike route paths, which don't carry the /v1 prefix at this point.
# Anything else, including routes added later, is 403 for a key: deny by default.
API_KEY_OPERATIONS = frozenset(
    {
        ("POST", "search"),
        ("GET", "list_documents"),
        ("GET", "get_document"),
        ("GET", "list_chunks"),
    }
)


def _key_not_allowed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="API keys are read-only: this route needs a login token",
    )


async def _key_user(request: Request, key: str) -> CurrentUser:
    principal = await api_key_repository.principal_for(hash_api_key(key))
    if principal is None:
        raise _credentials_error()
    route = request.scope.get("route")
    if (request.method, getattr(route, "name", None)) not in API_KEY_OPERATIONS:
        raise _key_not_allowed()
    set_tenant_id(principal.tenant_id)
    return CurrentUser(
        id=principal.user_id,
        tenant_id=principal.tenant_id,
        email=principal.email,
        # Never admin, even for a key an admin made: no admin-only reads (debug, traces).
        role=UserRole.member.value,
        created_at=principal.created_at,
        scope=principal.scope,
        api_key_id=principal.key_id,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(  # noqa: B008
        _bearer_scheme
    ),
    *,
    request: Request,
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if looks_like_api_key(credentials.credentials):
        return await _key_user(request, credentials.credentials)

    try:
        token_payload = decode_access_token(credentials.credentials)
    except InvalidToken:
        raise _credentials_error() from None

    user = await get_user_by_id(token_payload.tenant_id, token_payload.user_id)
    if user is None:
        raise _credentials_error()

    # The verified tenant, for log lines only; the middleware resets it per request.
    set_tenant_id(user.tenant_id)
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
