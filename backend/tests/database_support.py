"""Create owned, disposable databases; never reset a caller-supplied database."""

import re
from collections.abc import Mapping
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool


class DatabaseSafetyError(RuntimeError):
    pass


def configured_database_url(environ: Mapping[str, str]) -> URL | None:
    """Validate explicit test configuration before making any network connection."""
    if environ.get("FUMA_OPERATIONS_TEST_DATABASE_URL"):
        raise DatabaseSafetyError("Use only FUMA_TEST_DATABASE_URL for all database tests")
    raw = environ.get("FUMA_TEST_DATABASE_URL", "")
    opt_in = environ.get("FUMA_TEST_DATABASE_ALLOW_CREATE", "")
    if not raw and not opt_in:
        return None
    if not raw or opt_in != "1":
        raise DatabaseSafetyError(
            "Database tests require FUMA_TEST_DATABASE_URL and FUMA_TEST_DATABASE_ALLOW_CREATE=1"
        )
    try:
        url = make_url(raw)
        valid = (
            url.drivername == "postgresql+psycopg"
            and bool(url.host)
            and bool(url.username)
            and bool(re.fullmatch(r"[a-z][a-z0-9_]{0,57}_test", url.database or ""))
            and not url.query
            and (url.port is None or 1 <= url.port <= 65535)
        )
    except (ValueError, SQLAlchemyError):
        valid = False
    if not valid:
        # Never include the supplied URL or the provider's exception in output.
        raise DatabaseSafetyError(
            "Test URL must use postgresql+psycopg, an explicit host/user, a database ending "
            "in _test, and no query parameters"
        )
    return url


@contextmanager
def temporary_database(bootstrap: URL):
    """Yield a fresh database URL and drop only the database we successfully created."""
    database = "fuma_pytest_" + uuid4().hex
    engine = create_engine(
        bootstrap,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
    )
    try:
        try:
            connection = engine.connect()
        except SQLAlchemyError:
            raise DatabaseSafetyError(
                "Could not connect to the configured test PostgreSQL server"
            ) from None
        with connection:
            try:
                # No IF NOT EXISTS: collision or uncertain creation must never authorize deletion.
                connection.exec_driver_sql(f'CREATE DATABASE "{database}" TEMPLATE template0')
            except SQLAlchemyError:
                raise DatabaseSafetyError(
                    "Could not create a disposable test database; check the isolated server "
                    "and test role CREATEDB permission"
                ) from None
            try:
                yield bootstrap.set(database=database).render_as_string(hide_password=False)
            finally:
                try:
                    connection.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
                except SQLAlchemyError:
                    raise DatabaseSafetyError(
                        f"Could not remove owned temporary database {database}; "
                        "inspect this database on the isolated test server"
                    ) from None
    finally:
        engine.dispose()
