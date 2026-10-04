"""Explicit display default; no automatic stable/rollout selection."""

import sqlalchemy as sa
from alembic import op

revision = "0015_release_defaults"
down_revision = "0014_package_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "release_defaults",
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("applications.id"), primary_key=True),
        sa.Column("platform", sa.String(16), primary_key=True),
        sa.Column("publication_id", sa.Uuid(), sa.ForeignKey("publications.id"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("release_defaults")
