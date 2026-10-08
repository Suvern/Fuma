from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_migration_round_trip_and_singleton_constraint(monkeypatch, isolated_database_url):
    url = isolated_database_url.get_secret_value()
    monkeypatch.setenv("FUMA_DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT id, initialized_at FROM system_state")
            ).all() == [(1, None)]
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("INSERT INTO system_state (id) VALUES (2)"))
        command.check(config)
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.mark.integration
def test_notification_migration_copies_legacy_template_per_app(monkeypatch, isolated_database_url):
    from app.domains.applications.models import AppRecord
    from app.domains.auth.service import utcnow
    from app.domains.distribution.models import AppNotificationTemplate, IntegrationState
    from app.domains.distribution.notification_templates import DEFAULT_TEMPLATE, template_config

    url = isolated_database_url.get_secret_value()
    monkeypatch.setenv("FUMA_DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine(url)
    try:
        command.upgrade(config, "0019_task_authorization")
        legacy = {k: v for k, v in DEFAULT_TEMPLATE.items() if k != "sub_button_text"}
        legacy["title"] = "原有自定义标题"
        with Session(engine) as db:
            db.add(IntegrationState(key="release_notification_template", revision=7, data=legacy))
            apps = [
                AppRecord(
                    name=name,
                    public_slug=name,
                    platforms=["android"],
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                for name in ("migration-a", "migration-b")
            ]
            db.add_all(apps)
            db.commit()
            ids = [app.id for app in apps]
        command.upgrade(config, "head")
        command.check(config)
        with Session(engine) as db:
            for id in ids:
                assert db.get(AppNotificationTemplate, id).data == legacy
                value = template_config(db, db.get(AppRecord, id), "https://example.com")
                assert value["template"]["sub_button_text"] == "应用下载页"
            db.get(AppNotificationTemplate, ids[0]).data = {**legacy, "title": "仅 A"}
            db.commit()
            assert db.get(AppNotificationTemplate, ids[1]).data == legacy
            assert db.get(IntegrationState, "release_notification_template").data == legacy
        command.downgrade(config, "0019_task_authorization")
        with Session(engine) as db:
            assert db.get(IntegrationState, "release_notification_template").data == legacy
        command.upgrade(config, "head")
    finally:
        engine.dispose()
