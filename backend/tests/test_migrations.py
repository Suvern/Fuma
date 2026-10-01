import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
def test_migration_round_trip_and_singleton_constraint(monkeypatch):
    url = os.environ.get("FUMA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set FUMA_TEST_DATABASE_URL to an isolated, disposable PostgreSQL database")
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
