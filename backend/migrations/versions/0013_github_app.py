"""GitHub App configuration; PAT remains the default for existing connectors."""

import sqlalchemy as sa
from alembic import op

revision = "0013_github_app"
down_revision = "0012_cloud_storage"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "github_connectors",
        sa.Column("auth_kind", sa.String(16), server_default="pat", nullable=False),
    )
    op.alter_column("github_connectors", "auth_kind", server_default=None)
    op.add_column("github_connectors", sa.Column("app_id", sa.String(30), nullable=True))
    op.add_column("github_connectors", sa.Column("installation_id", sa.String(30), nullable=True))


def downgrade():
    for field in ["installation_id", "app_id", "auth_kind"]:
        op.drop_column("github_connectors", field)
