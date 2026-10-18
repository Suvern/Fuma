"""Reuse one encrypted provider credential across multiple bucket locations."""

import sqlalchemy as sa
from alembic import op

revision = "0027_storage_credentials"
down_revision = "0026_cos_manual_import"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "storage_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("encrypted_credentials", sa.String(length=4000), nullable=False),
        sa.Column("candidate_credentials", sa.String(length=4000), nullable=True),
        sa.Column("access_key_hint", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_storage_credentials"),
    )
    op.add_column(
        "storage_locations",
        sa.Column("credential_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_storage_locations_credential_id", "storage_locations", ["credential_id"])
    op.create_foreign_key(
        "fk_storage_locations_credential_id_storage_credentials",
        "storage_locations",
        "storage_credentials",
        ["credential_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_storage_locations_credential_id_storage_credentials",
        "storage_locations",
        type_="foreignkey",
    )
    op.drop_index("ix_storage_locations_credential_id", table_name="storage_locations")
    op.drop_column("storage_locations", "credential_id")
    op.drop_table("storage_credentials")
