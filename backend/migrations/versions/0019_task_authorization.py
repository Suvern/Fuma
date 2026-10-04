"""Keep task principals and explicit app audit scopes; do not guess legacy ownership."""

import sqlalchemy as sa
from alembic import op

revision = "0019_task_authorization"
down_revision = "0018_access_roles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("durable_tasks", sa.Column("created_actor_id", sa.Uuid(), nullable=True))
    op.add_column(
        "durable_tasks", sa.Column("actor_permission_revision", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_durable_tasks_created_actor_id_users",
        "durable_tasks",
        "users",
        ["created_actor_id"],
        ["id"],
    )
    op.add_column("audit_events", sa.Column("app_id", sa.Uuid(), nullable=True))
    op.create_index("ix_audit_events_app_id", "audit_events", ["app_id"])


def downgrade():
    op.drop_index("ix_audit_events_app_id", table_name="audit_events")
    op.drop_column("audit_events", "app_id")
    op.drop_constraint(
        "fk_durable_tasks_created_actor_id_users", "durable_tasks", type_="foreignkey"
    )
    op.drop_column("durable_tasks", "actor_permission_revision")
    op.drop_column("durable_tasks", "created_actor_id")
