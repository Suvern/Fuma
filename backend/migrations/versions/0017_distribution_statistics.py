"""Post-upgrade authorization timestamps and daily ASGI download observations."""

import sqlalchemy as sa
from alembic import op

revision = "0017_distribution_statistics"
down_revision = "0016_app_display_platforms"
branch_labels = None
depends_on = None


def upgrade():
    # Historical issuance timestamps are unknown; never fabricate measurements.
    op.add_column(
        "library_grants", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_library_grants_created_at", "library_grants", ["created_at"])
    op.create_table(
        "distribution_observations",
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("applications.id"), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in (
                "local_get_requests",
                "local_head_requests",
                "partial_get_requests",
                "interrupted_get_requests",
                "observed_bytes",
            )
        ],
    )


def downgrade():
    op.drop_table("distribution_observations")
    op.drop_index("ix_library_grants_created_at", table_name="library_grants")
    op.drop_column("library_grants", "created_at")
