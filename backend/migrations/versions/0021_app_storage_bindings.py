"""Bind Debug and Release package objects to per-App storage prefixes."""

import sqlalchemy as sa
from alembic import op

revision = "0021_app_storage_bindings"
down_revision = "0020_app_notification_templates"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_storage_bindings",
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("storage_location_id", sa.Uuid(), nullable=False),
        sa.Column("object_prefix", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "channel IN ('debug', 'release')", name="ck_app_storage_bindings_channel"
        ),
        sa.ForeignKeyConstraint(
            ["app_id"], ["applications.id"], ondelete="CASCADE", name="fk_app_storage_bindings_app"
        ),
        sa.ForeignKeyConstraint(
            ["storage_location_id"],
            ["storage_locations.id"],
            name="fk_app_storage_bindings_storage_location",
        ),
        sa.PrimaryKeyConstraint("app_id", "channel"),
        sa.UniqueConstraint("app_id", "channel", name="uq_app_storage_bindings_app_channel"),
    )


def downgrade():
    op.drop_table("app_storage_bindings")
