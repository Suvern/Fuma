import pytest
from kombu.utils.url import parse_url as parse_broker_url
from pydantic import ValidationError
from redis.connection import parse_url
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.infrastructure.database import build_engine


def test_split_environment_preserves_special_credentials(monkeypatch):
    # Synthetic values deliberately include URL delimiters and non-ASCII characters.
    password = "test@:/?#%$ 空格"
    values = {
        "DATABASE_HOST": "db.internal",
        "DATABASE_PORT": "5433",
        "DATABASE_NAME": "mobile_builds",
        "DATABASE_USER": "fuma@service",
        "DATABASE_PASSWORD": password,
        "REDIS_HOST": "cache.internal",
        "REDIS_PORT": "6380",
        "REDIS_DB": "3",
        "REDIS_USERNAME": "worker@fuma",
        "REDIS_PASSWORD": password,
    }
    monkeypatch.delenv("FUMA_DATABASE_URL", raising=False)
    monkeypatch.delenv("FUMA_REDIS_URL", raising=False)
    for key, value in values.items():
        monkeypatch.setenv(f"FUMA_{key}", value)
    settings = Settings()
    engine = build_engine(settings)
    try:
        assert engine.url.host == "db.internal"
        assert engine.url.port == 5433
        assert engine.url.database == "mobile_builds"
        assert engine.url.username == "fuma@service"
        assert engine.url.password == password
    finally:
        engine.dispose()
    redis = parse_url(settings.redis_dsn.get_secret_value())
    assert redis["host"] == "cache.internal"
    assert redis["port"] == 6380
    assert redis["db"] == 3
    assert redis["username"] == "worker@fuma"
    assert redis["password"] == password
    broker = parse_broker_url(settings.redis_dsn.get_secret_value())
    assert broker["password"] == password
    assert broker["userid"] == "worker@fuma"
    assert broker["virtual_host"] == "3"
    assert password not in repr(settings)
    assert password not in str(settings.database_dsn)
    assert password not in str(settings.redis_dsn)


def test_empty_credentials_and_ipv6():
    settings = Settings(database_host="::1", redis_host="[::1]")
    database = make_url(settings.database_dsn.get_secret_value())
    redis = parse_url(settings.redis_dsn.get_secret_value())
    assert database.host == redis["host"] == "::1"
    assert database.password is None
    assert "password" not in redis
    assert "username" not in redis


def test_legacy_url_overrides_and_empty_url_fallback():
    settings = Settings(
        database_url="postgresql+psycopg://legacy@db:5432/previous",
        redis_url="redis://cache:6379/4",
        database_name="new_name",
        redis_db=2,
    )
    assert make_url(settings.database_dsn.get_secret_value()).database == "previous"
    assert parse_url(settings.redis_dsn.get_secret_value())["db"] == 4
    settings = Settings(database_url="", redis_url="", database_name="new_name", redis_db=2)
    assert make_url(settings.database_dsn.get_secret_value()).database == "new_name"
    assert parse_url(settings.redis_dsn.get_secret_value())["db"] == 2


@pytest.mark.parametrize(
    "fields",
    [
        {"database_port": 0},
        {"redis_port": 65536},
        {"redis_db": -1},
        {"database_name": ""},
        {"database_host": "postgresql://db"},
        {"redis_host": ""},
    ],
)
def test_invalid_connection_fields_fail_at_startup(fields):
    with pytest.raises(ValidationError):
        Settings(**fields)
