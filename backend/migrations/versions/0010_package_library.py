"""M2 library tables, without changing legacy Debug entries."""

from alembic import op

revision = "0010_package_library"
down_revision = "0009_app_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE packages (
	id UUID NOT NULL,
	app_id UUID NOT NULL,
	platform VARCHAR(16) NOT NULL,
	mode VARCHAR(16) NOT NULL,
	file_name VARCHAR(255) NOT NULL,
	size_bytes BIGINT NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	package_identifier VARCHAR(255) NOT NULL,
	version_name VARCHAR(100) NOT NULL,
	build_number VARCHAR(100) NOT NULL,
	min_os VARCHAR(100),
	architectures JSON NOT NULL,
	signer_fingerprints JSON NOT NULL,
	signature_status VARCHAR(100) NOT NULL,
	parser_version VARCHAR(100) NOT NULL,
	source_kind VARCHAR(16) NOT NULL,
	state VARCHAR(16) NOT NULL,
	internal_notes VARCHAR(2000) NOT NULL,
	revision INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_packages PRIMARY KEY (id),
	CONSTRAINT uq_packages_app_id UNIQUE (app_id, platform, mode, sha256),
	CONSTRAINT fk_packages_app_id_applications
        FOREIGN KEY(app_id) REFERENCES applications (id)
)
    """)
    op.execute("""
CREATE INDEX ix_packages_app_id ON packages (app_id)
    """)
    op.execute("""
CREATE TABLE upload_sessions (
	id UUID NOT NULL,
	app_id UUID NOT NULL,
	actor_id UUID NOT NULL,
	file_name VARCHAR(255) NOT NULL,
	declared_size BIGINT NOT NULL,
	platform VARCHAR(16) NOT NULL,
	mode VARCHAR(16) NOT NULL,
	chunk_size INTEGER NOT NULL,
	expected_parts INTEGER NOT NULL,
	parts JSON NOT NULL,
	state VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	task_id UUID,
	package_id UUID,
	error_message VARCHAR(500),
	CONSTRAINT pk_upload_sessions PRIMARY KEY (id),
	CONSTRAINT fk_upload_sessions_app_id_applications
        FOREIGN KEY(app_id) REFERENCES applications (id),
	CONSTRAINT fk_upload_sessions_actor_id_users
        FOREIGN KEY(actor_id) REFERENCES users (id),
	CONSTRAINT fk_upload_sessions_task_id_durable_tasks
        FOREIGN KEY(task_id) REFERENCES durable_tasks (id),
	CONSTRAINT fk_upload_sessions_package_id_packages
        FOREIGN KEY(package_id) REFERENCES packages (id)
)
    """)
    op.execute("""
CREATE INDEX ix_upload_sessions_app_id ON upload_sessions (app_id)
    """)
    op.execute("""
CREATE TABLE versions (
	id UUID NOT NULL,
	app_id UUID NOT NULL,
	display_name VARCHAR(100) NOT NULL,
	mode VARCHAR(16) NOT NULL,
	release_notes VARCHAR(10000) NOT NULL,
	revision INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_versions PRIMARY KEY (id),
	CONSTRAINT fk_versions_app_id_applications
        FOREIGN KEY(app_id) REFERENCES applications (id)
)
    """)
    op.execute("""
CREATE INDEX ix_versions_app_id ON versions (app_id)
    """)
    op.execute("""
CREATE TABLE publications (
	id UUID NOT NULL,
	app_id UUID NOT NULL,
	version_id UUID NOT NULL,
	platform VARCHAR(16) NOT NULL,
	mode VARCHAR(16) NOT NULL,
	state VARCHAR(16) NOT NULL,
	file_set_frozen BOOLEAN NOT NULL,
	revision INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_publications PRIMARY KEY (id),
	CONSTRAINT fk_publications_app_id_applications
        FOREIGN KEY(app_id) REFERENCES applications (id),
	CONSTRAINT fk_publications_version_id_versions
        FOREIGN KEY(version_id) REFERENCES versions (id)
)
    """)
    op.execute("""
CREATE INDEX ix_publications_app_id ON publications (app_id)
    """)
    op.execute("""
CREATE INDEX ix_publications_version_id ON publications (version_id)
    """)
    op.execute("""
CREATE TABLE publication_packages (
	publication_id UUID NOT NULL,
	package_id UUID NOT NULL,
	CONSTRAINT pk_publication_packages PRIMARY KEY (publication_id, package_id),
	CONSTRAINT fk_publication_packages_publication_id_publications
        FOREIGN KEY(publication_id) REFERENCES publications (id),
	CONSTRAINT fk_publication_packages_package_id_packages
        FOREIGN KEY(package_id) REFERENCES packages (id)
)
    """)


def downgrade() -> None:
    op.drop_table("publication_packages")
    op.drop_table("publications")
    op.drop_table("versions")
    op.drop_table("upload_sessions")
    op.drop_table("packages")
