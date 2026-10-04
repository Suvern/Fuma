"""Release matching rules and durable polling schedules."""

import sqlalchemy as sa
from alembic import op

revision = "0007_release_policies"
down_revision = "0006_initial_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_release_policies",
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("applications.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("auto_enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_result", sa.JSON()),
        sa.Column("last_task_id", sa.Uuid()),
    )
    op.create_index(
        "ix_github_release_policies_next_check_at", "github_release_policies", ["next_check_at"]
    )


def downgrade() -> None:
    op.drop_table("github_release_policies")
