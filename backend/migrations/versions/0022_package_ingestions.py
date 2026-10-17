"""Persist COS package event intake and verification state."""

import sqlalchemy as sa
from alembic import op

revision = "0022_package_ingestions"
down_revision = "0021_app_storage_bindings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "package_ingestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("object_key", sa.String(length=600), nullable=False),
        sa.Column("object_size", sa.BigInteger(), nullable=False),
        sa.Column("object_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_key", sa.String(length=600), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("build", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], name="fk_package_ingestions_app"),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["actions_rules.id"], name="fk_package_ingestions_rule"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["durable_tasks.id"], name="fk_package_ingestions_task"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_package_ingestions_event_id"),
        sa.CheckConstraint("channel IN ('debug', 'release')", name="ck_package_ingestions_channel"),
    )
    op.create_index("ix_package_ingestions_app_id", "package_ingestions", ["app_id"])
    op.create_index("ix_package_ingestions_state", "package_ingestions", ["state"])


def downgrade():
    op.drop_index("ix_package_ingestions_state", table_name="package_ingestions")
    op.drop_index("ix_package_ingestions_app_id", table_name="package_ingestions")
    op.drop_table("package_ingestions")
