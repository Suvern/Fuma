"""Persistent accounts, sessions, apps, idempotency and audit."""

import sqlalchemy as sa
from alembic import op

revision = "0002_core"
down_revision = "0001_system_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("username", sa.String(100), unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(512)),
        sa.Column("tenant_key", sa.String(200)),
        sa.Column("open_id", sa.String(200)),
        sa.UniqueConstraint("tenant_key", "open_id"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("authenticated_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("eligibility_until", sa.DateTime(timezone=True)),
        sa.Column("feishu_config_revision", sa.Integer()),
    )
    op.create_table(
        "auth_rate_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("public_slug", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("platforms", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("repository", sa.JSON()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "app_creation_requests",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(200)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(200)),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("summary", sa.String(500), nullable=False),
    )


def downgrade() -> None:
    for name in (
        "audit_events",
        "app_creation_requests",
        "applications",
        "auth_rate_buckets",
        "auth_sessions",
        "users",
    ):
        op.drop_table(name)
