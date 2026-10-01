"""Durable task execution fenced by a PostgreSQL session lock.

The lock lives on a dedicated connection, across domain service commits. Duplicate
Redis deliveries and expired leases cannot execute concurrently. Process death
releases the connection lock; the scheduler redelivers unfinished database work.
"""

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord, DeliveryRecord, EventRecord, TaskRecord
from app.domains.distribution.service import RetryLater, digest, state
from app.infrastructure import models  # noqa: F401
from app.infrastructure.database import build_engine
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def execute_task(engine, settings, task_id):
    task_id = UUID(str(task_id))
    key = int(digest(f"execution:{task_id}")[:15], 16)
    with engine.connect() as fence:
        owned = fence.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        fence.commit()
        if not owned:
            return
        try:
            with Session(engine) as db:
                task = db.get(TaskRecord, task_id)
                if not task or task.state not in {"queued", "running"}:
                    return
                if task.next_check_at and task.next_check_at > utcnow():
                    return
                task.state, task.phase, task.updated_at = "running", "running", utcnow()
                task.lease_until = utcnow() + timedelta(seconds=60)
                task.attempts += 1
                state(db, "worker", locked=True).data = {"last_seen_at": utcnow().isoformat()}
                db.commit()
                try:
                    dispatch(db, settings, task)
                except RetryLater as wait:
                    task.state, task.phase = "queued", "waiting"
                    task.next_check_at = utcnow() + timedelta(seconds=wait.delay)
                except Exception as exc:
                    db.rollback()
                    task = db.get(TaskRecord, task_id)
                    task.state, task.phase = "failed", "failed"
                    task.error_code = exc.code if isinstance(exc, AppError) else "TASK_FAILED"
                    task.error_message = (
                        exc.message
                        if isinstance(exc, AppError)
                        else "任务执行失败，请重试或检查配置"
                    )
                    if task.kind == "cache_download":
                        from app.domains.distribution.packages import mark_cache_failed

                        entry = db.get(DebugRecord, UUID(task.resource_id))
                        if entry:
                            mark_cache_failed(db, entry, task.error_code)
                    elif task.kind == "chat_sync":
                        snapshot = state(db, "chats", locked=True)
                        snapshot.data = {
                            **snapshot.data,
                            "sync_state": "failed",
                            "sync_error_code": task.error_code,
                        }
                    logger.warning("Task failed: id=%s type=%s", task.id, type(exc).__name__)
                else:
                    task.state, task.phase, task.progress = "succeeded", "done", 100
                    task.error_code, task.error_message = None, None
                    if task.kind == "build_event":
                        event = db.get(EventRecord, UUID(task.resource_id))
                        task.state = {
                            "partial_success": "partial_success",
                            "failed": "failed",
                            "unknown": "unknown",
                        }.get(event.state, "succeeded")
                        failed = next(
                            (s for s in reversed(event.stages) if s.get("error_code")), None
                        )
                        if failed:
                            task.error_code = failed["error_code"]
                            task.error_message = failed.get("error_message")
                    if task.kind == "notification":
                        ids = (
                            [task.resource_id]
                            if task.resource_id
                            else task.payload.get("delivery_ids", [])
                        )
                        rows = [db.get(DeliveryRecord, UUID(i)) for i in ids]
                        outcomes = {row.state for row in rows if row}
                        if "unknown" in outcomes:
                            task.state = "unknown"
                        elif "failed" in outcomes:
                            task.state = "partial_success" if "succeeded" in outcomes else "failed"
                task.updated_at, task.lease_until = utcnow(), None
                db.commit()
        finally:
            fence.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            fence.commit()


def dispatch(db, settings, task):
    if task.kind == "release_sync":
        from app.domains.github.service import sync_releases

        sync_releases(db, task.app_id, settings)
    elif task.kind == "chat_sync":
        from app.domains.distribution.feishu import sync_chats

        sync_chats(db, settings)
    elif task.kind == "cache_download":
        from app.domains.distribution.packages import download_cache

        download_cache(db, settings, UUID(task.resource_id), task.id)
    elif task.kind == "cache_cleanup":
        from app.domains.distribution.packages import cleanup_cache

        cleanup_cache(db, settings, task.payload.get("scope", "expired"))
    elif task.kind == "notification":
        from app.domains.distribution.feishu import send_delivery

        ids = [task.resource_id] if task.resource_id else task.payload.get("delivery_ids", [])
        for delivery_id in ids:
            row = db.get(DeliveryRecord, UUID(delivery_id))
            if row:
                send_delivery(db, settings, row.id)
    elif task.kind == "build_event":
        from app.domains.distribution.actions import process_event

        process_event(db, settings, UUID(task.resource_id))
    else:
        raise AppError(422, "UNKNOWN_TASK_KIND", "未知任务类型")


@celery_app.task(name="fuma.execute", ignore_result=True)
def run_task(task_id):
    settings = Settings()
    engine = build_engine(settings)
    try:
        execute_task(engine, settings, task_id)
    finally:
        engine.dispose()


@celery_app.task(name="fuma.heartbeat", ignore_result=True)
def heartbeat():
    engine = build_engine(Settings())
    try:
        with Session(engine) as db:
            state(db, "worker", locked=True).data = {"last_seen_at": utcnow().isoformat()}
            db.commit()
    finally:
        engine.dispose()
