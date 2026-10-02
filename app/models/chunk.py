import uuid

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        # No separate index on document_id alone: it's the leading column of
        # this composite unique, which already covers that lookup.
        UniqueConstraint("document_id", "chunk_index"),
        Index("ix_chunks_tenant_id", "tenant_id"),
        Index("ix_chunks_parent_id", "parent_id"),
    )

    # No default: the id is computed deterministically by the repository that
    # creates chunk rows (see app/core/ids.py), since the same id is reused as
    # the Qdrant point id. A missing id must fail loudly, not fall back to a
    # random UUID.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
