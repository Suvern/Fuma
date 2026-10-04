from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("provider_app_id", "tenant_key", "open_id"),
        CheckConstraint("global_role IN ('admin', 'maintainer', 'downloader')", name="user_role"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    username: Mapped[str | None] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(512))
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    tenant_key: Mapped[str | None] = mapped_column(String(200))
    open_id: Mapped[str | None] = mapped_column(String(200))
    provider_app_id: Mapped[str | None] = mapped_column(String(200))
    identity_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    global_role: Mapped[str] = mapped_column(
        String(16), default="downloader", server_default="downloader"
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    permission_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    permission_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppRoleRecord(Base):
    __tablename__ = "app_roles"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), primary_key=True)


class RoleChangeRecord(Base):
    __tablename__ = "member_role_changes"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    permission_revision: Mapped[int]
    before_rules: Mapped[dict] = mapped_column(JSON)
    after_rules: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eligibility_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feishu_config_revision: Mapped[int | None] = mapped_column(Integer)


class RateBucket(Base):
    __tablename__ = "auth_rate_buckets"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
