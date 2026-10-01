"""GitHub credentials and atomic complete Release snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0003_github"
down_revision = "0002_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_connectors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("github_login", sa.String(200)),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("last_test_status", sa.String(16), nullable=False),
        sa.Column("last_error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "github_connector_creation_requests",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
    )
    op.create_table(
        "github_repository_syncs",
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("applications.id"), primary_key=True),
        sa.Column("repository_id", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("releases", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("github_repository_syncs")
    op.drop_table("github_connector_creation_requests")
    op.drop_table("github_connectors")
