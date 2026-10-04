import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from redis import Redis
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.actions import router as actions_router
from app.api.applications import router as applications_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.distribution_statistics import router as distribution_statistics_router
from app.api.feishu import router as feishu_router
from app.api.github import router as github_router
from app.api.health import router as health_router
from app.api.integration_docs import router as integration_docs_router
from app.api.library import router as library_router
from app.api.library_imports import router as library_imports_router
from app.api.library_management import router as library_management_router
from app.api.members import router as members_router
from app.api.operations import router as operations_router
from app.api.packages import router as packages_router
from app.api.schemas import ErrorResponse
from app.api.self_sessions import router as self_sessions_router
from app.api.storage import router as storage_router
from app.core.config import Settings
from app.core.errors import install_error_handlers, unexpected_error_response
from app.core.key_store import ensure_encryption_key
from app.domains.auth.service import initialize_admin
from app.infrastructure.database import build_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = build_engine(config)
        app.state.redis = Redis.from_url(
            config.redis_dsn.get_secret_value(),
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            ensure_encryption_key(app.state.engine, config)
            initialize_admin(app.state.engine)
            yield
        finally:
            app.state.redis.close()
            app.state.engine.dispose()

    app = FastAPI(
        title="Fuma API",
        version="0.1.0",
        description="Fuma M1 foundation. Business endpoints will be added incrementally.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        responses={
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )

    app.state.settings = config
    from app.domains.distribution.feishu import feishu_config

    app.state.sso_enabled = lambda db: all(
        feishu_config(db, config)[key] for key in ("enabled", "verified")
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            # Handle before Starlette re-raises to Uvicorn's raw traceback logger.
            response = unexpected_error_response(request, exc)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.method == "HEAD":
            response = Response(status_code=response.status_code, headers=dict(response.headers))
        return response

    install_error_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(integration_docs_router, prefix="/api/v1")
    app.include_router(storage_router, prefix="/api/v1")
    app.include_router(library_imports_router, prefix="/api/v1")
    app.include_router(library_management_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(self_sessions_router, prefix="/api/v1")
    app.include_router(members_router, prefix="/api/v1")
    app.include_router(applications_router, prefix="/api/v1")
    app.include_router(distribution_statistics_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(github_router, prefix="/api/v1")
    app.include_router(feishu_router, prefix="/api/v1")
    app.include_router(packages_router, prefix="/api/v1")
    app.include_router(operations_router, prefix="/api/v1")
    app.include_router(actions_router, prefix="/api/v1")
    app.include_router(library_router, prefix="/api/v1")
    return app


app = create_app()
