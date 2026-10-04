from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class GithubConnector(Base):
    __tablename__ = "github_connectors"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    encrypted_token: Mapped[str] = mapped_column(Text)
    auth_kind: Mapped[str] = mapped_column(String(16), default="pat")
    app_id: Mapped[str | None] = mapped_column(String(30))
    installation_id: Mapped[str | None] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    github_login: Mapped[str | None] = mapped_column(String(200))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str] = mapped_column(String(16), default="untested")
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GithubConnectorCreation(Base):
    __tablename__ = "github_connector_creation_requests"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64))
    connector_id: Mapped[UUID] = mapped_column()


class GithubRepositorySync(Base):
    __tablename__ = "github_repository_syncs"

    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), primary_key=True)
    repository_id: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), default="never")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    # Replace only after ALL release and asset pages have completed successfully.
    releases: Mapped[list[dict]] = mapped_column(JSON, default=list)


class GithubReleasePolicy(Base):
    __tablename__ = "github_release_policies"

    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    settings: Mapped[dict] = mapped_column(JSON)
    auto_enabled: Mapped[bool] = mapped_column(default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_task_id: Mapped[UUID | None] = mapped_column()
