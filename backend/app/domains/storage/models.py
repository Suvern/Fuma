from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class StorageLocation(Base):
    __tablename__ = "storage_locations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(16))
    region: Mapped[str] = mapped_column(String(40))
    bucket: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(100))
    read_mode: Mapped[str] = mapped_column(String(16))
    encrypted_credentials: Mapped[str] = mapped_column(String(4000))
    candidate_credentials: Mapped[str | None] = mapped_column(String(4000))
    enabled: Mapped[bool] = mapped_column(default=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    revision: Mapped[int] = mapped_column(default=1)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(String(500))
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("durable_tasks.id"))


class StoredObject(Base):
    __tablename__ = "stored_objects"
    __table_args__ = (UniqueConstraint("location_id", "object_key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    location_id: Mapped[UUID] = mapped_column(ForeignKey("storage_locations.id"), index=True)
    package_id: Mapped[UUID | None] = mapped_column(ForeignKey("packages.id"), index=True)
    publication_id: Mapped[UUID | None] = mapped_column(ForeignKey("publications.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(600))
    kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
