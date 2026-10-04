import hashlib
import json
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, text

from app.core.errors import AppError
from app.domains.auth.service import utcnow
from app.domains.distribution.models import IdempotencyRecord, IntegrationState, TaskRecord


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def lock(db, key: str) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(digest(key)[:15], 16)})


def state(db, key: str, *, locked=False) -> IntegrationState:
    if locked:
        lock(db, f"state:{key}")
    row = (
        db.scalar(
            select(IntegrationState)
            .where(IntegrationState.key == key)
            .execution_options(populate_existing=True)
        )
        if locked
        else db.get(IntegrationState, key)
    )
    if row is None:
        if not locked:
            lock(db, f"state:{key}")
            row = db.scalar(
                select(IntegrationState)
                .where(IntegrationState.key == key)
                .execution_options(populate_existing=True)
            )
            if row is not None:
                return row
        row = IntegrationState(key=key, revision=0, data={})
        db.add(row)
        db.flush()
    return row


def enqueue(db, kind, resource_id=None, app_id=None, payload=None, dedupe_key=None):
    if dedupe_key:
        lock(db, dedupe_key)
        existing = db.scalar(select(TaskRecord).where(TaskRecord.dedupe_key == dedupe_key))
        if existing:
            if existing.state in {"queued", "running"}:
                return existing
            existing.dedupe_key = None
            db.flush()
    now = utcnow()
    task = TaskRecord(
        kind=kind,
        state="queued",
        phase="queued",
        resource_id=resource_id,
        app_id=app_id,
        payload=payload or {},
        dedupe_key=dedupe_key,
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.flush()
    return task


def task_accepted(task):
    return {"task_id": task.id, "status_url": f"/api/v1/tasks/{task.id}"}


def task_dto(task):
    names = (
        "id",
        "kind",
        "state",
        "phase",
        "progress",
        "app_id",
        "resource_id",
        "attempts",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
        "next_check_at",
    )
    return {
        **{n: getattr(task, n) for n in names},
        "can_retry": (task.state == "failed" and task.kind not in {"notification", "build_event"})
        or (task.state == "partial_success" and task.kind in {"release_sync", "release_import"}),
    }


def page(items, page=1, page_size=20, **extra):
    return {
        "items": items[(page - 1) * page_size : page * page_size],
        "page": page,
        "page_size": page_size,
        "total": len(items),
        **extra,
    }


def idem_begin(db, scope, key, body):
    try:
        UUID(key or "")
    except (ValueError, TypeError):
        raise AppError(
            422, "IDEMPOTENCY_KEY_REQUIRED", "请提供 UUID 格式的 Idempotency-Key"
        ) from None
    composite = f"{scope}:{key}"
    lock(db, composite)
    row = db.get(IdempotencyRecord, composite)
    if row and row.expires_at <= utcnow():
        db.delete(row)
        db.flush()
        row = None
    if row and row.body_hash != digest(body):
        raise AppError(409, "IDEMPOTENCY_CONFLICT", "相同请求标识不能用于不同内容")
    return composite, row


def idem_save(db, composite, body, data, ttl=86400):
    row = IdempotencyRecord(
        key=composite,
        body_hash=digest(body),
        data=json.loads(json.dumps(data, default=str)),
        expires_at=utcnow() + timedelta(seconds=ttl),
    )
    db.add(row)


def must_get(db, model, identity):
    row = db.get(model, identity)
    if row is None:
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "资源不存在或不可访问")
    return row


class RetryLater(Exception):
    def __init__(self, delay=15):
        self.delay = delay
