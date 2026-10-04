"""M2 package identity configuration; M1 entries remain unparsed and unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0008_app_package_ids"
down_revision = "0007_release_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allowed_package_ids",
        sa.Column(
            "app_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("platform", sa.String(16), primary_key=True),
        sa.Column("mode", sa.String(16), primary_key=True),
        sa.Column("normalized_identifier", sa.String(255), primary_key=True),
        sa.Column("identifier", sa.String(255), nullable=False),
        sa.CheckConstraint("platform IN ('android', 'ios')", name="ck_package_id_platform"),
        sa.CheckConstraint("mode IN ('debug', 'release')", name="ck_package_id_mode"),
    )


def downgrade() -> None:
    op.drop_table("allowed_package_ids")
