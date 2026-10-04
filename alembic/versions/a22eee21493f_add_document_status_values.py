"""add document status values

Revision ID: a22eee21493f
Revises: 5f261360d306
Create Date: 2026-10-04 12:01:23.403613

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a22eee21493f"
down_revision: str | Sequence[str] | None = "5f261360d306"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'uploaded'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'chunked'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'embedding'")


def downgrade() -> None:
    # Postgres cannot remove values from an enum type. Leaving them in place is
    # harmless; rows never write them after this revision is rolled back.
    pass
