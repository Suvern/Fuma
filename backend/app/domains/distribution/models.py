"""Persistent distribution state; Redis carries wakeups, never the only copy of work."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database import Base


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntegrationState(Base):
    __tablename__ = "integration_states"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class AppNotificationTemplate(Base):
    __tablename__ = "app_notification_templates"
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id"))
    config_revision: Mapped[int]
    purpose: Mapped[str] = mapped_column(String(16))
    return_to: Mapped[str] = mapped_column(String(2048))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(default=False)


class BindingProofRecord(Base):
    __tablename__ = "feishu_binding_proofs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id"))
    config_revision: Mapped[int]
    app_id: Mapped[str] = mapped_column(String(128))
    tenant_key: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(default=False)


class ChatRecord(Base):
    __tablename__ = "feishu_chats"
    chat_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(500))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    membership: Mapped[str] = mapped_column(String(16), default="joined")
    send_status: Mapped[str] = mapped_column(String(16), default="unverified")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskRecord(Timestamped, Base):
    __tablename__ = "durable_tasks"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(100), default="queued")
    progress: Mapped[int | None]
    app_id: Mapped[UUID | None] = mapped_column(ForeignKey("applications.id"))
    created_actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_permission_revision: Mapped[int | None]
    resource_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CacheRecord(Base):
    __tablename__ = "source_caches"
    source_identity: Mapped[str] = mapped_column(String(64), primary_key=True)
    storage_key: Mapped[UUID] = mapped_column(default=uuid4, unique=True)
    file_name: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(__import__("sqlalchemy").BigInteger)
    cache_state: Mapped[str] = mapped_column(String(16), default="missing")
    downloaded_bytes: Mapped[int] = mapped_column(__import__("sqlalchemy").BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    cache_error_code: Mapped[str | None] = mapped_column(String(100))
    cache_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legacy_storage_keys: Mapped[list] = mapped_column(JSON, default=list)


class DebugRecord(Timestamped, Base):
    __tablename__ = "debug_entries"
    __table_args__ = (UniqueConstraint("app_id", "source_identity"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    persistent_package_id: Mapped[UUID | None] = mapped_column(ForeignKey("packages.id"))
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    source_identity: Mapped[str] = mapped_column(String(64))
    cache_identity: Mapped[str | None] = mapped_column(ForeignKey("source_caches.source_identity"))
    cache_record: Mapped[CacheRecord | None] = relationship()
    connector_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(default=1)
    enabled: Mapped[bool] = mapped_column(default=True)
    platform: Mapped[str] = mapped_column(String(16))
    file_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(__import__("sqlalchemy").BigInteger)
    version_name: Mapped[str | None] = mapped_column(String(100))
    build_number: Mapped[str | None] = mapped_column(String(100))
    source_tag: Mapped[str] = mapped_column(String(255))
    source: Mapped[dict] = mapped_column(JSON)
    cache_state: Mapped[str] = mapped_column(String(16), default="missing")
    downloaded_bytes: Mapped[int] = mapped_column(__import__("sqlalchemy").BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    cache_error_code: Mapped[str | None] = mapped_column(String(100))
    cache_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrantRecord(Base):
    __tablename__ = "download_grants"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("debug_entries.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TransferLease(Base):
    __tablename__ = "transfer_leases"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("debug_entries.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RuleRecord(Timestamped, Base):
    __tablename__ = "actions_rules"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    revision: Mapped[int] = mapped_column(default=1)
    data: Mapped[dict] = mapped_column(JSON)
    token_hash: Mapped[str | None] = mapped_column(String(64))
    token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventRecord(Timestamped, Base):
    __tablename__ = "build_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    rule_id: Mapped[UUID] = mapped_column(ForeignKey("actions_rules.id"))
    identity: Mapped[str] = mapped_column(String(64), unique=True)
    data: Mapped[dict] = mapped_column(JSON)
    rule_snapshot: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32), default="received")
    stages: Mapped[list] = mapped_column(JSON, default=list)
    assets: Mapped[list] = mapped_column(JSON, default=list)


class PackageIngestionRecord(Timestamped, Base):
    __tablename__ = "package_ingestions"
    __table_args__ = (UniqueConstraint("event_id", name="uq_package_ingestions_event_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    rule_id: Mapped[UUID] = mapped_column(ForeignKey("actions_rules.id"))
    event_id: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str] = mapped_column(String(16))
    object_key: Mapped[str] = mapped_column(String(600))
    object_size: Mapped[int] = mapped_column(__import__("sqlalchemy").BigInteger)
    object_sha256: Mapped[str] = mapped_column(String(64))
    manifest_key: Mapped[str] = mapped_column(String(600))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    build: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(32), default="received", index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("durable_tasks.id"))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryRecord(Timestamped, Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("build_events.id"))
    app_id: Mapped[UUID | None] = mapped_column(ForeignKey("applications.id"))
    chat_id: Mapped[str] = mapped_column(String(128))
    chat_name: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))
    card: Mapped[dict] = mapped_column(JSON)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
