"""Track COS Release ingestion and its pending publication."""

import sqlalchemy as sa
from alembic import op

revision = "0025_cos_release_publication"
down_revision = "0024_cos_notification_rule"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("package_ingestions", sa.Column("package_id", sa.Uuid(), nullable=True))
    op.add_column("package_ingestions", sa.Column("publication_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_package_ingestions_package_id_packages",
        "package_ingestions",
        "packages",
        ["package_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_package_ingestions_publication_id_publications",
        "package_ingestions",
        "publications",
        ["publication_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_package_ingestions_publication_id_publications",
        "package_ingestions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_package_ingestions_package_id_packages",
        "package_ingestions",
        type_="foreignkey",
    )
    op.drop_column("package_ingestions", "publication_id")
    op.drop_column("package_ingestions", "package_id")
