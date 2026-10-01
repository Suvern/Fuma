from alembic import context

from app.core.config import Settings
from app.domains.applications.models import AppCreation, AppRecord  # noqa: F401
from app.domains.audit.models import AuditRecord  # noqa: F401
from app.domains.auth.models import AuthSession, RateBucket, User  # noqa: F401
from app.domains.distribution import models as distribution_models  # noqa: F401
from app.domains.github import models as github_models  # noqa: F401
from app.domains.system.models import SystemState  # noqa: F401
from app.infrastructure.database import Base, build_engine

target_metadata = Base.metadata
settings = Settings()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_dsn.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
