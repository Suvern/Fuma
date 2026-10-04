"""Short-lived capabilities for private immutable publication files."""

import sqlalchemy as sa
from alembic import op

revision = "0011_library_grants"
down_revision = "0010_package_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "library_grants",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("publication_id", sa.Uuid(), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("package_id", sa.Uuid(), sa.ForeignKey("packages.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("library_grants")
