"""Private cloud originals and independently reclaimable public copies."""

import sqlalchemy as sa
from alembic import op

revision = "0012_cloud_storage"
down_revision = "0011_library_grants"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE storage_locations (
	id UUID NOT NULL,
	name VARCHAR(100) NOT NULL,
	provider VARCHAR(16) NOT NULL,
	region VARCHAR(40) NOT NULL,
	bucket VARCHAR(100) NOT NULL,
	prefix VARCHAR(100) NOT NULL,
	read_mode VARCHAR(16) NOT NULL,
	encrypted_credentials VARCHAR(4000) NOT NULL,
	candidate_credentials VARCHAR(4000),
	enabled BOOLEAN NOT NULL,
	is_default BOOLEAN NOT NULL,
	status VARCHAR(16) NOT NULL,
	revision INTEGER NOT NULL,
	checked_at TIMESTAMP WITH TIME ZONE,
	capabilities JSON NOT NULL,
	error_message VARCHAR(500),
	task_id UUID,
	CONSTRAINT pk_storage_locations PRIMARY KEY (id),
	CONSTRAINT fk_storage_locations_task_id_durable_tasks
        FOREIGN KEY(task_id) REFERENCES durable_tasks (id)
)

    """)
    op.execute("""
CREATE TABLE stored_objects (
	id UUID NOT NULL,
	location_id UUID NOT NULL,
	package_id UUID,
	publication_id UUID,
	object_key VARCHAR(600) NOT NULL,
	kind VARCHAR(16) NOT NULL,
	state VARCHAR(16) NOT NULL,
	size_bytes BIGINT NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_stored_objects PRIMARY KEY (id),
	CONSTRAINT uq_stored_objects_location_id UNIQUE (location_id, object_key),
	CONSTRAINT fk_stored_objects_location_id_storage_locations
        FOREIGN KEY(location_id) REFERENCES storage_locations (id),
	CONSTRAINT fk_stored_objects_package_id_packages
        FOREIGN KEY(package_id) REFERENCES packages (id),
	CONSTRAINT fk_stored_objects_publication_id_publications
        FOREIGN KEY(publication_id) REFERENCES publications (id)
)

    """)
    op.execute("""CREATE INDEX ix_stored_objects_location_id ON stored_objects (location_id)
    """)
    op.execute("""CREATE INDEX ix_stored_objects_package_id ON stored_objects (package_id)
    """)
    op.execute("""CREATE INDEX ix_stored_objects_publication_id ON stored_objects (publication_id)
    """)
    op.add_column(
        "packages",
        sa.Column(
            "storage_location_id", sa.Uuid(), sa.ForeignKey("storage_locations.id"), nullable=True
        ),
    )
    op.add_column(
        "upload_sessions",
        sa.Column(
            "storage_location_id", sa.Uuid(), sa.ForeignKey("storage_locations.id"), nullable=True
        ),
    )
    op.add_column(
        "publications",
        sa.Column(
            "public_storage_id", sa.Uuid(), sa.ForeignKey("storage_locations.id"), nullable=True
        ),
    )
    op.add_column(
        "publications",
        sa.Column("access_state", sa.String(20), server_default="private", nullable=False),
    )
    op.alter_column("publications", "access_state", server_default=None)
    op.add_column(
        "publications",
        sa.Column("access_task_id", sa.Uuid(), sa.ForeignKey("durable_tasks.id"), nullable=True),
    )
    op.add_column("publications", sa.Column("access_error", sa.String(500), nullable=True))


def downgrade():
    for name in ["access_error", "access_task_id", "access_state", "public_storage_id"]:
        op.drop_column("publications", name)
    op.drop_column("upload_sessions", "storage_location_id")
    op.drop_column("packages", "storage_location_id")
    op.drop_table("stored_objects")
    op.drop_table("storage_locations")
