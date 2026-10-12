"""Read-only API keys (M9 9.2). Management is scoped by tenant; lookup is by key hash."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from app.models.api_key import ApiKey
from app.models.user import User
from app.repositories.session import session_scope


@dataclass(frozen=True)
class ApiKeyRecord:
    id: UUID
    name: str
    prefix: str
    scope: str
    created_by: UUID
    created_at: datetime


@dataclass(frozen=True)
class KeyPrincipal:
    """Who a valid key acts as: its tenant, and its creator (for rate limits and logs)."""

    key_id: UUID
    tenant_id: UUID
    user_id: UUID
    email: str
    scope: str
    created_at: datetime


def _record(row: ApiKey) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scope=row.scope,
        created_by=row.created_by,
        created_at=row.created_at,
    )


async def create_key(
    tenant_id: UUID, user_id: UUID, *, name: str, prefix: str, key_hash: str
) -> ApiKeyRecord:
    async with session_scope() as session:
        row = ApiKey(
            tenant_id=tenant_id,
            created_by=user_id,
            name=name,
            prefix=prefix,
            key_hash=key_hash,
            scope="read",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _record(row)


async def list_active_keys(tenant_id: UUID) -> list[ApiKeyRecord]:
    async with session_scope() as session:
        rows = await session.scalars(
            select(ApiKey)
            .where(ApiKey.tenant_id == tenant_id, ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
        )
        return [_record(row) for row in rows]


async def revoke_key(tenant_id: UUID, key_id: UUID) -> bool:
    """False if there's no active key with this id in the tenant."""
    async with session_scope() as session:
        result = await session.execute(
            update(ApiKey)
            .where(
                ApiKey.id == key_id,
                ApiKey.tenant_id == tenant_id,
                ApiKey.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
        return cast(CursorResult[Any], result).rowcount > 0


async def principal_for(key_hash: str) -> KeyPrincipal | None:
    """The tenant and creator behind an active key; None if unknown or revoked."""
    async with session_scope() as session:
        row = (
            await session.execute(
                select(ApiKey.id, ApiKey.tenant_id, ApiKey.scope, User.id, User.email)
                .join(
                    User,
                    (User.id == ApiKey.created_by)
                    & (User.tenant_id == ApiKey.tenant_id),
                )
                .add_columns(User.created_at)
                .where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
            )
        ).first()
    if row is None:
        return None
    key_id, tenant_id, scope, user_id, email, created_at = row
    return KeyPrincipal(
        key_id=key_id,
        tenant_id=tenant_id,
        user_id=user_id,
        email=email,
        scope=scope,
        created_at=created_at,
    )
