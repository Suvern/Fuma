"""Associate standalone COS notifications with their Actions rule."""

import sqlalchemy as sa
from alembic import op

revision = "0024_cos_notification_rule"
down_revision = "0023_cos_debug_ingestion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_deliveries",
        sa.Column("rule_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_deliveries_rule_id_actions_rules",
        "notification_deliveries",
        "actions_rules",
        ["rule_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_notification_deliveries_rule_id_actions_rules",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_column("notification_deliveries", "rule_id")
