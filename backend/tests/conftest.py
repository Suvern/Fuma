"""CI must never silently turn unavailable integration dependencies into a green run."""

import os
from unittest.mock import Mock

import pytest


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
