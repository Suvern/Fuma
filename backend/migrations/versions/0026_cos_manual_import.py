"""Allow administrator-initiated COS imports without a CI rule."""

import sqlalchemy as sa
from alembic import op

revision = "0026_cos_manual_import"
down_revision = "0025_cos_release_publication"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "package_ingestions",
        "rule_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade():
    op.alter_column(
        "package_ingestions",
        "rule_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
