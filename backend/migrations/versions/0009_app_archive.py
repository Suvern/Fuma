"""Explicit archive state; existing applications and distribution remain unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0009_app_archive"
down_revision = "0008_app_package_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("archived_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("applications", "archived_at")
