"""Allow Debug entries to originate from COS events without a GitHub connector."""

from alembic import op

revision = "0023_cos_debug_ingestion"
down_revision = "0022_package_ingestions"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("debug_entries", "connector_id", nullable=True)


def downgrade():
    op.alter_column("debug_entries", "connector_id", nullable=False)
