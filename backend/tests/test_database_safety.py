"""Safety gates and owned-database cleanup, without any PostgreSQL connection."""

from unittest.mock import MagicMock

import pytest
from database_support import (
    DatabaseSafetyError,
    configured_database_url,
    temporary_database,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

URL = "postgresql+psycopg://fuma@127.0.0.1:55499/fuma_test"


def configuration(url=URL, allow="1"):
    return {"FUMA_TEST_DATABASE_URL": url, "FUMA_TEST_DATABASE_ALLOW_CREATE": allow}


def test_no_configuration_never_falls_back_to_application_database():
    assert configured_database_url({"FUMA_DATABASE_URL": "postgresql://app@prod/live"}) is None


@pytest.mark.parametrize(
    "config",
    [
        configuration(allow=""),
        configuration(allow="true"),
        configuration(url=""),
        configuration(url="not-a-database-url"),
        configuration(url="sqlite:///fuma_test"),
        configuration(url="postgresql://fuma@localhost/fuma_test"),
        configuration(url="postgresql+psycopg://fuma@localhost/fuma"),
        configuration(url="postgresql+psycopg://fuma@localhost/postgres"),
        configuration(url="postgresql+psycopg://fuma@localhost/template1"),
        configuration(url="postgresql+psycopg:///fuma_test"),
        configuration(url="postgresql+psycopg://localhost/fuma_test"),
        configuration(url=URL + "?dbname=live"),
        configuration(url=URL + "?host=production"),
        configuration(url=URL + "?service=production"),
        configuration(url=URL.replace("55499", "99999")),
        configuration(url=URL.replace("fuma_test", "a" * 60 + "_test")),
        {"FUMA_OPERATIONS_TEST_DATABASE_URL": URL},
    ],
)
def test_unsafe_configuration_is_rejected_before_connecting(config, monkeypatch):
    create = MagicMock()
    monkeypatch.setattr("database_support.create_engine", create)
    with pytest.raises(DatabaseSafetyError):
        configured_database_url(config)
    create.assert_not_called()


def test_custom_host_port_user_and_encoded_password_are_preserved():
    url = configured_database_url(
        configuration("postgresql+psycopg://tester:synthetic%40password@db-test:5433/team_test")
    )
    assert (url.host, url.port, url.username, url.password, url.database) == (
        "db-test",
        5433,
        "tester",
        "synthetic@password",
        "team_test",
    )


def test_invalid_url_error_does_not_echo_credentials():
    with pytest.raises(DatabaseSafetyError) as error:
        configured_database_url(configuration("postgresql+psycopg://u:synthetic-secret@db/live"))
    assert "synthetic-secret" not in str(error.value)


@pytest.fixture
def database_engine(monkeypatch):
    engine = MagicMock()
    connection = engine.connect.return_value
    connection.__enter__.return_value = connection
    monkeypatch.setattr("database_support.create_engine", lambda *args, **kwargs: engine)
    return engine, connection


def test_only_fresh_random_database_is_used_and_dropped(database_engine):
    engine, connection = database_engine
    bootstrap = configured_database_url(configuration())
    names = []
    for _ in range(2):
        with temporary_database(bootstrap) as value:
            url = make_url(value)
            assert url.database.startswith("fuma_pytest_")
            assert url.set(database=bootstrap.database) == bootstrap
            assert url.database != bootstrap.database
            names.append(url.database)
    assert names[0] != names[1]
    assert [call.args[0] for call in connection.exec_driver_sql.call_args_list] == [
        command
        for name in names
        for command in [
            f'CREATE DATABASE "{name}" TEMPLATE template0',
            f'DROP DATABASE "{name}" WITH (FORCE)',
        ]
    ]
    assert engine.dispose.call_count == 2


def test_test_failure_still_cleans_up_only_the_created_database(database_engine):
    engine, connection = database_engine
    with pytest.raises(ValueError, match="test failed"):
        with temporary_database(configured_database_url(configuration())) as value:
            name = make_url(value).database
            raise ValueError("test failed")
    connection.exec_driver_sql.assert_called_with(f'DROP DATABASE "{name}" WITH (FORCE)')
    engine.dispose.assert_called_once()


def test_creation_failure_or_collision_never_drops_existing_database(database_engine):
    engine, connection = database_engine
    connection.exec_driver_sql.side_effect = OperationalError(
        "CREATE DATABASE", {}, Exception("synthetic-private-provider-error")
    )
    with pytest.raises(DatabaseSafetyError) as error:
        with temporary_database(configured_database_url(configuration())):
            pytest.fail("A failed creation must not yield a database URL")
    assert connection.exec_driver_sql.call_count == 1
    assert "synthetic-private-provider-error" not in str(error.value)
    engine.dispose.assert_called_once()


def test_connection_failure_never_drops_any_database(database_engine):
    engine, connection = database_engine
    engine.connect.side_effect = OperationalError("connect", {}, Exception("synthetic-secret"))
    with pytest.raises(DatabaseSafetyError) as error:
        with temporary_database(configured_database_url(configuration())):
            pytest.fail("An unavailable server must not yield a database URL")
    connection.exec_driver_sql.assert_not_called()
    assert "synthetic-secret" not in str(error.value)
    engine.dispose.assert_called_once()


def test_cleanup_failure_is_reported_without_provider_details(database_engine):
    engine, connection = database_engine
    connection.exec_driver_sql.side_effect = [
        None,
        OperationalError("DROP DATABASE", {}, Exception("synthetic-secret")),
    ]
    with pytest.raises(DatabaseSafetyError, match="owned temporary database") as error:
        with temporary_database(configured_database_url(configuration())):
            pass
    assert "synthetic-secret" not in str(error.value)
    engine.dispose.assert_called_once()
