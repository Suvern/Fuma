"""CI must never silently turn unavailable integration dependencies into a green run."""

import gc
import os
from unittest.mock import Mock

import pytest
from database_support import (
    DatabaseSafetyError,
    configured_database_url,
    temporary_database,
)
from pydantic import SecretStr


@pytest.fixture
def isolated_database_url():
    try:
        bootstrap = configured_database_url(os.environ)
    except DatabaseSafetyError as error:
        pytest.fail(str(error), pytrace=False)
    if bootstrap is None:
        pytest.skip(
            "Database tests require an isolated FUMA_TEST_DATABASE_URL and "
            "FUMA_TEST_DATABASE_ALLOW_CREATE=1"
        )
    with temporary_database(bootstrap) as url:
        try:
            # Keep credentials redacted if pytest renders fixture parameters on failure.
            yield SecretStr(url)
        finally:
            # TestClient may leave cancelled streaming iterators in reference cycles.
            # Finalize their DB-backed leases before removing this test's database.
            gc.collect()


@pytest.fixture(autouse=True)
def initial_password_log(monkeypatch):
    logger = Mock()
    monkeypatch.setattr("app.domains.auth.service.initial_password_logger.warning", logger)
    return logger


def pytest_sessionfinish(session, exitstatus):
    if not os.environ.get("CI"):
        return
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if reporter and reporter.stats.get("skipped"):
        reporter.write_sep("=", "CI requires all PostgreSQL integration tests; skips are failures")
        session.exitstatus = 1
