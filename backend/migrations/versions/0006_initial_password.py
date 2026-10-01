"""Automatic administrator initialization and persisted encryption-key identity."""

import sqlalchemy as sa
from alembic import op

revision = "0006_initial_password"
down_revision = "0005_shared_source_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("system_state", sa.Column("encryption_key_digest", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("system_state", "encryption_key_digest")
    op.drop_column("users", "must_change_password")
