import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiKey(Base):
    """A read-only credential bound to one tenant (M9 9.2), for the MCP server.

    Only the key's SHA-256 is stored; the key itself is shown once at creation. A revoked
    key is kept (revoked_at set) so its use can be refused and audited.
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_tenant_id", "tenant_id"),
        # The creator must be a user of this tenant, enforced by the database.
        ForeignKeyConstraint(
            ["created_by", "tenant_id"],
            ["users.id", "users.tenant_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # The first 12 characters ("nxk_" + 8), to recognise a key without revealing it.
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="read"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
