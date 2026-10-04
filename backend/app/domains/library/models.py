"""M2 immutable package contents, resumable uploads and explicit publications."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class UploadRecord(Base):
    __tablename__ = "upload_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    declared_size: Mapped[int] = mapped_column(BigInteger)
    platform: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(16))
    chunk_size: Mapped[int]
    expected_parts: Mapped[int]
    parts: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(16), default="receiving")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("durable_tasks.id"))
    package_id: Mapped[UUID | None] = mapped_column(ForeignKey("packages.id"))
    error_message: Mapped[str | None] = mapped_column(String(500))
    storage_location_id: Mapped[UUID | None] = mapped_column(ForeignKey("storage_locations.id"))
    source_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PackageRecord(Base):
    __tablename__ = "packages"
    __table_args__ = (UniqueConstraint("app_id", "platform", "mode", "sha256"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    platform: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(16))
    file_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    package_identifier: Mapped[str] = mapped_column(String(255))
    version_name: Mapped[str] = mapped_column(String(100))
    build_number: Mapped[str] = mapped_column(String(100))
    min_os: Mapped[str | None] = mapped_column(String(100))
    architectures: Mapped[list] = mapped_column(JSON, default=list)
    signer_fingerprints: Mapped[list] = mapped_column(JSON, default=list)
    signature_status: Mapped[str] = mapped_column(String(100))
    parser_version: Mapped[str] = mapped_column(String(100))
    source_kind: Mapped[str] = mapped_column(String(16), default="upload")
    state: Mapped[str] = mapped_column(String(16), default="ready")
    internal_notes: Mapped[str] = mapped_column(String(2000), default="")
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    storage_location_id: Mapped[UUID | None] = mapped_column(ForeignKey("storage_locations.id"))
    source_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class VersionRecord(Base):
    __tablename__ = "versions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(16))
    release_notes: Mapped[str] = mapped_column(String(10000))
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PublicationRecord(Base):
    __tablename__ = "publications"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("versions.id"), index=True)
    platform: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16), default="draft")
    file_set_frozen: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    public_storage_id: Mapped[UUID | None] = mapped_column(ForeignKey("storage_locations.id"))
    access_state: Mapped[str] = mapped_column(String(20), default="private")
    access_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("durable_tasks.id"))
    access_error: Mapped[str | None] = mapped_column(String(500))


class PublicationPackage(Base):
    __tablename__ = "publication_packages"
    publication_id: Mapped[UUID] = mapped_column(ForeignKey("publications.id"), primary_key=True)
    package_id: Mapped[UUID] = mapped_column(ForeignKey("packages.id"), primary_key=True)


class LibraryGrant(Base):
    __tablename__ = "library_grants"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    publication_id: Mapped[UUID] = mapped_column(ForeignKey("publications.id"))
    package_id: Mapped[UUID] = mapped_column(ForeignKey("packages.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class ReleaseDefault(Base):
    __tablename__ = "release_defaults"
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), primary_key=True)
    publication_id: Mapped[UUID | None] = mapped_column(ForeignKey("publications.id"))
    revision: Mapped[int] = mapped_column(default=0)
