"""Optional inline app icons and independent persistent platform switches."""

import sqlalchemy as sa
from alembic import op

revision = "0016_app_display_platforms"
down_revision = "0015_release_defaults"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "applications", sa.Column("icon_data", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "applications",
        sa.Column("disabled_platforms", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.alter_column("applications", "icon_data", server_default=None)
    op.alter_column("applications", "disabled_platforms", server_default=None)


def downgrade():
    op.drop_column("applications", "disabled_platforms")
    op.drop_column("applications", "icon_data")
