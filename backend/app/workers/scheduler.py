"""Database outbox scanner; safe to restart, no credentials in log messages."""

import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domains.auth.service import utcnow
from app.domains.distribution.models import TaskRecord
from app.domains.distribution.service import enqueue, state
from app.infrastructure import models  # noqa: F401
from app.infrastructure.database import build_engine
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def scan(engine, sent):
    now = utcnow()
    with Session(engine) as db:
        state(db, "scheduler", locked=True).data = {"last_seen_at": now.isoformat()}
        maintenance = state(db, "maintenance", locked=True)
        if (
            not maintenance.data.get("next_cleanup")
            or maintenance.data["next_cleanup"] <= now.isoformat()
        ):
            enqueue(
                db,
                "cache_cleanup",
                payload={"scope": "expired"},
                dedupe_key="cache_cleanup:expired",
            )
            maintenance.data = {"next_cleanup": (now + timedelta(minutes=5)).isoformat()}
        db.commit()
        from app.domains.github.releases import schedule_release_checks

        schedule_release_checks(db, now)
        db.commit()
        jobs = db.scalars(
            select(TaskRecord).where(
                or_(
                    TaskRecord.state == "queued",
                    (TaskRecord.state == "running") & (TaskRecord.lease_until < now),
                ),
                or_(TaskRecord.next_check_at.is_(None), TaskRecord.next_check_at <= now),
            )
        ).all()
        for job in jobs:
            if sent.get(job.id, 0) > time.monotonic() - 15:
                continue
            celery_app.send_task(
                "fuma.execute",
                args=[str(job.id)],
                queue="files"
                if job.kind in {"cache_download", "package_ingest", "publication_access"}
                else "general",
            )
            sent[job.id] = time.monotonic()
        active_ids = {job.id for job in jobs}
        for identity in list(sent):
            if identity not in active_ids:
                del sent[identity]
    celery_app.send_task("fuma.heartbeat", queue="general")


def main():
    logging.basicConfig(level=logging.WARNING)
    engine, sent, stopping = build_engine(Settings()), {}, False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            try:
                scan(engine, sent)
            except Exception as exc:
                logger.warning("Scheduler scan failed: type=%s", type(exc).__name__)
            for _ in range(50):
                if stopping:
                    break
                time.sleep(0.1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
