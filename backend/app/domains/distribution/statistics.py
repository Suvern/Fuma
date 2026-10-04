"""Aggregate server observations, without visitor identifiers or download tokens."""

import logging
from datetime import UTC, date, datetime
from uuid import UUID

import anyio
from sqlalchemy import BigInteger, Date, ForeignKey
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette.responses import FileResponse

from app.infrastructure.database import Base

COUNTERS = (
    "local_get_requests",
    "local_head_requests",
    "partial_get_requests",
    "interrupted_get_requests",
    "observed_bytes",
)


class DistributionObservation(Base):
    __tablename__ = "distribution_observations"
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    local_get_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    local_head_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    partial_get_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    interrupted_get_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    observed_bytes: Mapped[int] = mapped_column(BigInteger, default=0)


def record_observation(engine, app_id, day, counters):
    values = {name: counters[name] for name in COUNTERS}
    statement = insert(DistributionObservation).values(app_id=app_id, date=day, **values)
    statement = statement.on_conflict_do_update(
        index_elements=["app_id", "date"],
        set_={
            name: getattr(DistributionObservation, name) + statement.excluded[name]
            for name in COUNTERS
        },
    )
    with Session(engine) as db:
        db.execute(statement)
        db.commit()


class ObservedFileResponse(FileResponse):
    """Count bytes accepted by ASGI send, not verified client receipt or installation."""

    def __init__(self, *args, statistics_engine, statistics_app_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.statistics_engine = statistics_engine
        self.statistics_app_id = statistics_app_id

    async def __call__(self, scope, receive, send):
        method = scope.get("method", "GET")
        status, byte_count, complete = None, 0, False
        started = datetime.now(UTC).date()

        async def observed_send(message):
            nonlocal status, byte_count, complete
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                if method == "GET" and status in (200, 206):
                    byte_count += len(message.get("body", b""))
                if not message.get("more_body", False):
                    complete = True

        # Disable the optional zero-copy extension because it bypasses byte observations.
        observed_scope = {
            **scope,
            "extensions": {
                key: value
                for key, value in scope.get("extensions", {}).items()
                if key != "http.response.pathsend"
            },
        }
        try:
            await super().__call__(observed_scope, receive, observed_send)
        finally:
            counters = {
                "local_get_requests": int(method == "GET"),
                "local_head_requests": int(method == "HEAD"),
                "partial_get_requests": int(method == "GET" and status == 206),
                "interrupted_get_requests": int(method == "GET" and not complete),
                "observed_bytes": byte_count,
            }
            # Preserve cancellation while allowing the bounded, independent bookkeeping transaction.
            with anyio.CancelScope(shield=True):
                try:
                    await anyio.to_thread.run_sync(
                        record_observation,
                        self.statistics_engine,
                        self.statistics_app_id,
                        started,
                        counters,
                    )
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "Distribution observation unavailable: %s", type(exc).__name__
                    )
