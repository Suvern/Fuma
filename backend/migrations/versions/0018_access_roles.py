"""Explicit backend roles and provider-scoped Feishu identities."""

import sqlalchemy as sa
from alembic import op

revision = "0018_access_roles"
down_revision = "0017_distribution_statistics"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("provider_app_id", sa.String(200), nullable=True))
    op.add_column(
        "users", sa.Column("identity_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("global_role", sa.String(16), nullable=False, server_default="downloader"),
    )
    op.add_column(
        "users", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "users", sa.Column("permission_revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "users", sa.Column("permission_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE users SET global_role = 'admin' WHERE kind = 'local' AND username = 'admin'")
    # Only a recorded login against the current verified configuration establishes
    # historical provider scope. Unproven identities must log in again.
    op.execute("""
        UPDATE users AS u SET
          provider_app_id = c.data->>'app_id',
          identity_verified_at = (
            SELECT max(s.authenticated_at) FROM auth_sessions s
            WHERE s.user_id=u.id AND s.feishu_config_revision=c.revision
          )
        FROM integration_states c
        WHERE c.key='feishu' AND c.data->>'verified'='true'
          AND u.kind='feishu' AND u.tenant_key=c.data->>'tenant_key'
          AND EXISTS (SELECT 1 FROM auth_sessions s WHERE s.user_id=u.id
            AND s.feishu_config_revision=c.revision AND s.authenticated_at IS NOT NULL)
    """)
    op.drop_constraint("uq_users_tenant_key", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_provider_app_id", "users", ["provider_app_id", "tenant_key", "open_id"]
    )
    op.create_check_constraint(
        "user_role", "users", "global_role IN ('admin', 'maintainer', 'downloader')"
    )
    op.create_table(
        "app_roles",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("applications.id"), primary_key=True),
    )
    op.create_table(
        "member_role_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("permission_revision", sa.Integer(), nullable=False),
        sa.Column("before_rules", sa.JSON(), nullable=False),
        sa.Column("after_rules", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_member_role_changes_user_id", "member_role_changes", ["user_id"])


def downgrade():
    # Downgrading must not silently merge identities from different provider Apps.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM users WHERE tenant_key IS NOT NULL AND open_id IS NOT NULL
            GROUP BY tenant_key, open_id HAVING count(*) > 1) THEN
            RAISE EXCEPTION 'Cannot downgrade: provider-scoped identities require separate records';
          END IF;
        END $$;
    """)
    op.drop_index("ix_member_role_changes_user_id", table_name="member_role_changes")
    op.drop_table("member_role_changes")
    op.drop_table("app_roles")
    op.drop_constraint(op.f("ck_users_user_role"), "users", type_="check")
    op.drop_constraint("uq_users_provider_app_id", "users", type_="unique")
    op.create_unique_constraint("uq_users_tenant_key", "users", ["tenant_key", "open_id"])
    for name in (
        "permission_changed_at",
        "permission_revision",
        "active",
        "global_role",
        "identity_verified_at",
        "provider_app_id",
    ):
        op.drop_column("users", name)
