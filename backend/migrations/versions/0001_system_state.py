"""Create the singleton instance state without initializing an administrator."""

import sqlalchemy as sa
from alembic import op

revision = "0001_system_state"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "system_state",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_system_state_singleton")),
        sa.PrimaryKeyConstraint("id", name="pk_system_state"),
    )
    op.bulk_insert(table, [{"id": 1, "initialized_at": None}])


def downgrade() -> None:
    op.drop_table("system_state")
