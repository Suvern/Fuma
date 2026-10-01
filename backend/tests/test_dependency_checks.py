from unittest.mock import Mock

from redis.exceptions import TimeoutError as RedisTimeout
from sqlalchemy.exc import OperationalError

from app.infrastructure.health import check_dependencies


def test_dependency_checks_report_both_failures_without_raw_errors():
    engine, redis = Mock(), Mock()
    engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("private-db-detail"))
    redis.ping.side_effect = RedisTimeout("private-redis-detail")
    result = check_dependencies(engine, redis)
    assert result.model_dump() == {"database": "unavailable", "redis": "unavailable"}
    redis.ping.assert_called_once()


def test_redis_failure_does_not_hide_successful_database_probe():
    engine, redis = Mock(), Mock()
    engine.connect.return_value.__enter__ = Mock(return_value=Mock())
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    redis.ping.side_effect = RedisTimeout("timeout")
    result = check_dependencies(engine, redis)
    assert result.model_dump() == {"database": "ok", "redis": "unavailable"}
