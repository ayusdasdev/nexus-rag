"""tie conversation owner to its tenant

Revision ID: 3ccf8af42a82
Revises: 7043f21d7f44
Create Date: 2026-10-09 17:06:49.890005

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3ccf8af42a82"
down_revision: str | Sequence[str] | None = "7043f21d7f44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """conversations(user_id, tenant_id) must name a user of that tenant (M6 low finding)."""
    # Refuse, with a clear message, rather than fail half-way on rows that would break the FK.
    mismatched = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM conversations c JOIN users u ON u.id = c.user_id "
            "WHERE u.tenant_id <> c.tenant_id"
        )
        .scalar()
    )
    if mismatched:
        raise RuntimeError(
            f"{mismatched} conversation(s) belong to a user of another tenant; fix them first"
        )
    # The unique constraint must exist before the FK that references it.
    op.create_unique_constraint(op.f("uq_users_id"), "users", ["id", "tenant_id"])
    op.drop_constraint(
        op.f("fk_conversations_user_id_users"), "conversations", type_="foreignkey"
    )
    op.create_foreign_key(
        op.f("fk_conversations_user_id_users"),
        "conversations",
        "users",
        ["user_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Reverse order: drop the FK before the unique constraint it depends on.
    op.drop_constraint(
        op.f("fk_conversations_user_id_users"), "conversations", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_users_id"), "users", type_="unique")
    op.create_foreign_key(
        op.f("fk_conversations_user_id_users"),
        "conversations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
