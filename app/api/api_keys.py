"""Read-only API keys (M9 9.2): tenant-bound credentials for the MCP server.

Admins only. A key acts as a non-admin reader of its tenant and reaches only the read
allowlist in app/api/deps.py (API_KEY_OPERATIONS); a revoked key stops working at once.
"""

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import CurrentUser, get_current_user
from app.api.rate_limit import limit_default
from app.core.security import new_api_key
from app.models.user import UserRole
from app.repositories import api_key_repository
from app.repositories.api_key_repository import ApiKeyRecord
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyList, ApiKeyOut

router = APIRouter(
    prefix="/api-keys", tags=["api-keys"], dependencies=[Depends(limit_default)]
)


def _admin(user: CurrentUser) -> None:
    if user.role != UserRole.admin.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys are managed by admins",
        )


def _out(record: ApiKeyRecord) -> ApiKeyOut:
    return ApiKeyOut(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        scope=cast(Literal["read"], record.scope),
        created_by=record.created_by,
        created_at=record.created_at,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreated,
    summary="Create a read-only API key for this tenant (admins only)",
    responses={
        401: {"description": "Missing or invalid token"},
        403: {"description": "Not an admin, or called with an API key"},
        422: {"description": "Invalid body, including any tenant_id field"},
    },
)
async def create_api_key(
    request: ApiKeyCreate,
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> ApiKeyCreated:
    """Create a key bound to your tenant that can only search and read documents (for
    the MCP server). The key is in this response only; store it now."""
    _admin(user)
    key, key_hash = new_api_key()
    record = await api_key_repository.create_key(
        user.tenant_id, user.id, name=request.name, prefix=key[:12], key_hash=key_hash
    )
    return ApiKeyCreated(**_out(record).model_dump(), key=key)


@router.get(
    "",
    response_model=ApiKeyList,
    summary="List this tenant's active API keys (admins only)",
    responses={
        401: {"description": "Missing or invalid token"},
        403: {"description": "Not an admin, or called with an API key"},
    },
)
async def list_api_keys(
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> ApiKeyList:
    """Active keys of your tenant, newest first, without the keys themselves."""
    _admin(user)
    return ApiKeyList(
        items=[
            _out(r) for r in await api_key_repository.list_active_keys(user.tenant_id)
        ]
    )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key (admins only)",
    responses={
        401: {"description": "Missing or invalid token"},
        403: {"description": "Not an admin, or called with an API key"},
        404: {"description": "No active key with this id in your tenant"},
        422: {"description": "Malformed key id"},
    },
)
async def revoke_api_key(
    key_id: UUID,
    user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> Response:
    """Revoke a key of your tenant; it is refused (401) from the next request on."""
    _admin(user)
    if not await api_key_repository.revoke_key(user.tenant_id, key_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
