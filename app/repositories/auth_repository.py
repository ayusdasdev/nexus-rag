from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.repositories.session import session_scope


class EmailAlreadyExists(Exception):
    pass


@dataclass(frozen=True)
class TenantRecord:
    id: UUID
    name: str
    created_at: datetime


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    tenant_id: UUID
    email: str
    password_hash: str
    role: str
    created_at: datetime


def _to_user_record(row: User) -> UserRecord:
    return UserRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        email=row.email,
        password_hash=row.password_hash,
        role=row.role.value,
        created_at=row.created_at,
    )


async def create_tenant_and_admin_user(
    tenant_name: str, email: str, password_hash: str
) -> tuple[TenantRecord, UserRecord]:
    """Create a tenant and its first (admin) user in one transaction."""
    async with session_scope() as session:
        tenant = Tenant(name=tenant_name)
        session.add(tenant)
        await session.flush()

        user = User(
            tenant_id=tenant.id,
            email=email,
            password_hash=password_hash,
            role=UserRole.admin,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            # Closes the TOCTOU window between the service's pre-check and
            # this insert: the DB's unique constraint on email is the real
            # backstop if two signups race with the same email.
            await session.rollback()
            raise EmailAlreadyExists from exc

        await session.commit()

        return (
            TenantRecord(id=tenant.id, name=tenant.name, created_at=tenant.created_at),
            _to_user_record(user),
        )


async def get_user_by_email(email: str) -> UserRecord | None:
    async with session_scope() as session:
        result = await session.execute(select(User).where(User.email == email))
        row = result.scalars().first()
        return None if row is None else _to_user_record(row)


async def get_user_by_id(tenant_id: UUID, user_id: UUID) -> UserRecord | None:
    async with session_scope() as session:
        result = await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
        row = result.scalars().first()
        return None if row is None else _to_user_record(row)
