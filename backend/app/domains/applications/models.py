from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class AppRecord(Base):
    __tablename__ = "applications"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    public_slug: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(2000), default="")
    platforms: Mapped[list[str]] = mapped_column(JSON)
    disabled_platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    icon_data: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    repository: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppCreation(Base):
    __tablename__ = "app_creation_requests"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64))
    app_id: Mapped[UUID] = mapped_column()


class AllowedPackageIdRecord(Base):
    __tablename__ = "allowed_package_ids"
    __table_args__ = (
        CheckConstraint("platform IN ('android', 'ios')", name="ck_package_id_platform"),
        CheckConstraint("mode IN ('debug', 'release')", name="ck_package_id_mode"),
    )

    app_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True
    )
    platform: Mapped[str] = mapped_column(String(16), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), primary_key=True)
    normalized_identifier: Mapped[str] = mapped_column(String(255), primary_key=True)
    identifier: Mapped[str] = mapped_column(String(255))
