from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas import DependencyChecks


def check_dependencies(engine: Engine, redis: Redis) -> DependencyChecks:
    checks = DependencyChecks(database="unavailable", redis="unavailable")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks.database = "ok"
    except SQLAlchemyError:
        pass
    try:
        if redis.ping():
            checks.redis = "ok"
    except (OSError, RedisError):
        pass
    return checks
