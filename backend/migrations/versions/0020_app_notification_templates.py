"""Copy the legacy global card into independently editable application templates."""

import sqlalchemy as sa
from alembic import op

revision = "0020_app_notification_templates"
down_revision = "0019_task_authorization"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_notification_templates",
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("applications.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    # Keep existing customized content, including for archived applications. New apps
    # start with the system default; the global row is no longer read by the application.
    op.execute(
        """INSERT INTO app_notification_templates (app_id, revision, data)
        SELECT applications.id, 1, integration_states.data
        FROM applications CROSS JOIN integration_states
        WHERE integration_states.key = 'release_notification_template'"""
    )


def downgrade():
    # The legacy global configuration is preserved; per-app edits cannot be merged into it.
    op.drop_table("app_notification_templates")
