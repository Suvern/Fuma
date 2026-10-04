import os
import shutil
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import select

from app.api import contracts as dto
from app.api.app_access import ScopedManager
from app.api.dependencies import CSRF, DB, Admin, require_revision
from app.core.errors import AppError
from app.domains.access.authorization import manageable_app_ids
from app.domains.auth.service import utcnow
from app.domains.distribution.models import TaskRecord, TransferLease
from app.domains.distribution.packages import cache_root, cache_settings, cache_usage
from app.domains.distribution.service import (
    enqueue,
    idem_begin,
    idem_save,
    lock,
    must_get,
    page,
    state,
    task_accepted,
    task_dto,
)
from app.infrastructure.health import check_dependencies

router = APIRouter(tags=["Operations"])

TaskKind = Literal[
    "release_sync",
    "release_import",
    "chat_sync",
    "cache_download",
    "build_event",
    "notification",
    "cache_cleanup",
    "package_ingest",
    "package_delete",
    "storage_probe",
    "publication_access",
]
TASK_NAMES = {
    "release_sync": "Release 同步",
    "release_import": "Release 批量导入",
    "chat_sync": "群聊同步",
    "cache_download": "缓存下载",
    "build_event": "构建事件",
    "notification": "通知发送",
    "cache_cleanup": "缓存清理",
    "package_ingest": "安装包解析入库",
    "package_delete": "安装包文件清理",
    "storage_probe": "云存储连接测试",
    "publication_access": "公开副本与访问收回",
}


@router.get("/tasks", response_model=dto.TaskPage, operation_id="list_tasks")
def tasks(
    db: DB,
    admin: ScopedManager,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: str | None = None,
    app_id: UUID | None = None,
    state_filter: Annotated[str | None, Query(alias="state")] = None,
    kind: TaskKind | None = None,
):
    stmt = select(TaskRecord).order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
    ids = manageable_app_ids(db, admin)
    if ids is not None:
        stmt = stmt.where(TaskRecord.app_id.in_(ids))
    rows = db.scalars(stmt).all()
    keyword = (q or "").strip().casefold()
    return page(
        [
            task_dto(r)
            for r in rows
            if (not app_id or r.app_id == app_id)
            and (not state_filter or r.state == state_filter)
            and (not kind or r.kind == kind)
            and (
                not keyword
                or any(
                    keyword in value.casefold()
                    for value in (r.kind, TASK_NAMES.get(r.kind, ""), r.resource_id or "")
                )
            )
        ],
        page_number,
        page_size,
    )


@router.get("/tasks/{id}", response_model=dto.Task, operation_id="get_task")
def task(id: UUID, db: DB, admin: ScopedManager):
    return task_dto(must_get(db, TaskRecord, id))


@router.post(
    "/tasks/{id}/retry", response_model=dto.TaskAccepted, status_code=202, operation_id="retry_task"
)
def retry_task(
    id: UUID,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    lock(db, f"task:{id}")
    row = must_get(db, TaskRecord, id)
    key, previous = idem_begin(db, f"retry_task:{id}", idempotency_key, {})
    if previous:
        return previous.data
    partial_release = row.state == "partial_success" and row.kind in {
        "release_sync",
        "release_import",
    }
    if (row.state != "failed" and not partial_release) or row.kind in {
        "notification",
        "build_event",
        "package_ingest",
        "storage_probe",
        "publication_access",
    }:
        raise AppError(409, "NOT_RETRYABLE", "请通过对应业务详情页重试，未知通知结果需单独确认")
    row.state, row.phase, row.error_code, row.error_message = "queued", "queued", None, None
    row.updated_at, row.next_check_at = utcnow(), None
    row.created_actor_id = admin.user.id
    row.actor_permission_revision = admin.user.permission_revision
    result = task_accepted(row)
    idem_save(db, key, {}, result)
    db.commit()
    return result


def cache_dto(db, settings):
    cfg = cache_settings(db)
    usage = cache_usage(db)
    root = cache_root(settings)
    leases = db.scalars(select(TransferLease).where(TransferLease.expires_at > utcnow())).all()
    return {
        **cfg.data,
        "revision": cfg.revision,
        **usage,
        "free_disk_bytes": shutil.disk_usage(root).free,
        "active_leases": len(leases),
    }


@router.get("/settings/cache", response_model=dto.CacheSettings, operation_id="get_cache_settings")
def get_cache(request: Request, response: Response, db: DB, admin: Admin):
    result = cache_dto(db, request.app.state.settings)
    response.headers["ETag"] = f'"{result["revision"]}"'
    db.commit()
    return result


@router.put(
    "/settings/cache", response_model=dto.CacheSettings, operation_id="update_cache_settings"
)
def update_cache(
    body: dto.CacheSettingsUpdate,
    request: Request,
    response: Response,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    lock(db, "cache_capacity")
    cfg = cache_settings(db)
    require_revision(if_match, cfg.revision)
    if body.max_file_bytes > body.budget_bytes:
        raise AppError(422, "INVALID_CACHE_BUDGET", "单文件上限不得超过总配额")
    cfg.data, cfg.revision = body.model_dump(mode="json"), cfg.revision + 1
    db.commit()
    return get_cache(request, response, db, admin)


@router.post(
    "/system/cache/cleanup",
    response_model=dto.TaskAccepted,
    status_code=202,
    operation_id="cleanup_cache",
)
def cleanup(
    body: dto.CacheCleanupRequest,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    payload = body.model_dump(mode="json")
    key, previous = idem_begin(db, "cleanup", idempotency_key, payload)
    if previous:
        return previous.data
    task = enqueue(db, "cache_cleanup", payload=payload, dedupe_key=f"cache_cleanup:{body.scope}")
    result = task_accepted(task)
    idem_save(db, key, payload, result)
    db.commit()
    return result


@router.get("/system/health", response_model=dto.SystemHealth, operation_id="get_system_health")
def health(request: Request, db: DB, admin: Admin):
    settings = request.app.state.settings
    now = utcnow()

    def heartbeat(kind):
        value = state(db, kind).data.get("last_seen_at")
        stamp = datetime.fromisoformat(value) if value else None
        return (
            "unknown"
            if not stamp
            else "ok"
            if stamp > now - timedelta(seconds=30)
            else "unavailable"
        ), stamp

    worker, last = heartbeat("worker")
    scheduler, _ = heartbeat("scheduler")
    try:
        root = cache_root(settings)
        writable, free = os.access(root, os.W_OK), shutil.disk_usage(root).free
    except (OSError, AppError):
        writable, free = False, 0
    checks = check_dependencies(request.app.state.engine, request.app.state.redis)
    return {
        "api": "ok",
        "database": checks.database,
        "redis": checks.redis,
        "worker": worker,
        "worker_last_seen_at": last,
        "scheduler": scheduler,
        "cache_writable": writable,
        "cache_free_bytes": free,
        "public_origin": settings.site_url,
    }
