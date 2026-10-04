"""Parsed sources and explicit private migration of legacy entries."""

import sqlalchemy as sa
from alembic import op

revision = "0014_package_sources"
down_revision = "0013_github_app"
branch_labels = None
depends_on = None


def upgrade():
    for table in ["packages", "upload_sessions"]:
        op.add_column(table, sa.Column("source_snapshot", sa.JSON(), nullable=True))
    op.add_column(
        "debug_entries",
        sa.Column("persistent_package_id", sa.Uuid(), sa.ForeignKey("packages.id"), nullable=True),
    )


def downgrade():
    op.drop_column("debug_entries", "persistent_package_id")
    for table in ["packages", "upload_sessions"]:
        op.drop_column(table, "source_snapshot")
