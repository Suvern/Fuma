import os
import re
import secrets
import stat
import threading
from datetime import timedelta
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import contracts as dto
from app.api.app_access import ScopedManager
from app.api.dependencies import CSRF, DB, require_downloader, require_revision
from app.core.errors import AppError, error_response
from app.domains.applications.models import AppRecord
from app.domains.applications.service import platform_enabled, require_platform_enabled
from app.domains.audit.service import record_audit
from app.domains.auth.service import AuthContext, token_hash, utcnow
from app.domains.distribution.feishu import verify_download_context
from app.domains.distribution.models import DebugRecord, GrantRecord, TransferLease
from app.domains.distribution.packages import (
    cache_lock_key,
    cache_path,
    cache_settings,
    catalog_app,
    catalog_entry,
    create_entries,
    ensure_cache,
    entry_dto,
    mark_cache_missing,
    sort_entries,
    touch_cache,
)
from app.domains.distribution.service import (
    idem_begin,
    idem_save,
    lock,
    must_get,
    page,
    state,
    task_accepted,
)
from app.domains.github.crypto import SecretBox

router = APIRouter(tags=["Packages"])
Downloader = Annotated[AuthContext, Depends(require_downloader)]


def visible_entry(db, id):
    entry = must_get(db, DebugRecord, id)
    app = db.get(AppRecord, entry.app_id)
    if not entry.enabled or not platform_enabled(app, entry.platform):
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "资源不存在或不可访问")
    return entry


@router.get(
    "/apps/{id}/debug-entries", response_model=dto.DebugEntryPage, operation_id="list_debug_entries"
)
def entries(
    id: UUID,
    request: Request,
    db: DB,
    admin: ScopedManager,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: str | None = None,
    platform: str | None = None,
    sort: Literal["source_updated_at", "imported_at"] = "source_updated_at",
):
    must_get(db, AppRecord, id)
    rows = db.scalars(
        select(DebugRecord).where(DebugRecord.app_id == id).order_by(DebugRecord.created_at.desc())
    ).all()
    return page(
        [
            entry_dto(r, request.app.state.settings)
            for r in sort_entries(rows, sort)
            if (
                not q
                or q.casefold() in (r.file_name + r.source_tag + (r.version_name or "")).casefold()
            )
            and (not platform or r.platform == platform)
        ],
        page_number,
        page_size,
    )


@router.post(
    "/apps/{id}/debug-entries",
    response_model=dto.DebugEntryBatch,
    status_code=201,
    operation_id="create_debug_entries",
)
def select_entries(
    id: UUID,
    body: dto.DebugEntryCreate,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    app = must_get(db, AppRecord, id)
    payload = body.model_dump(mode="json")
    key, previous = idem_begin(db, f"entries:{id}", idempotency_key, payload)
    if previous:
        return previous.data
    result = create_entries(db, app, payload, request.app.state.settings)
    idem_save(db, key, payload, result)
    record_audit(
        db,
        action="debug_entries.create",
        resource_type="app",
        resource_id=str(id),
        actor_id=str(admin.user.id),
        request_id=request.state.request_id,
        summary="从 GitHub Release 选择 Debug 安装包",
    )
    db.commit()
    return result


@router.get("/debug-entries/{id}", response_model=dto.DebugEntry, operation_id="get_debug_entry")
def entry(id: UUID, request: Request, response: Response, db: DB, admin: ScopedManager):
    row = must_get(db, DebugRecord, id)
    response.headers["ETag"] = f'"{row.revision}"'
    return entry_dto(row, request.app.state.settings)


@router.patch(
    "/debug-entries/{id}", response_model=dto.DebugEntry, operation_id="update_debug_entry"
)
def update_entry(
    id: UUID,
    body: dto.DebugEntryUpdate,
    request: Request,
    response: Response,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    row = must_get(db, DebugRecord, id)
    if body.enabled:
        from app.api.applications import get_app

        if get_app(db, row.app_id, lock=True).archived_at:
            raise AppError(409, "APP_ARCHIVED", "归档应用不能重新启用安装包")
        require_platform_enabled(db.get(AppRecord, row.app_id), row.platform)
    lock(db, cache_lock_key(row))
    db.refresh(row)
    require_revision(if_match, row.revision)
    row.enabled, row.updated_at = body.enabled, utcnow()
    row.revision += 1
    record_audit(
        db,
        action="debug_entry.update",
        resource_type="debug_entry",
        resource_id=str(id),
        actor_id=str(admin.user.id),
        request_id=request.state.request_id,
        summary="更新 Debug 条目启用状态",
    )
    db.commit()
    return entry(id, request, response, db, admin)


@router.post(
    "/debug-entries/{id}/precache",
    response_model=dto.TaskAccepted,
    status_code=202,
    operation_id="precache_debug_entry",
)
def precache(
    id: UUID,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    row = must_get(db, DebugRecord, id)
    key, previous = idem_begin(db, f"precache:{id}", idempotency_key, {})
    if previous:
        return previous.data
    task = ensure_cache(db, row)
    result = task_accepted(task)
    idem_save(db, key, {}, result)
    db.commit()
    return result


@router.get("/catalog/apps", response_model=dto.CatalogAppPage, operation_id="list_catalog_apps")
def catalog_apps(
    db: DB,
    downloader: Downloader,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: str | None = None,
):
    verify_download_context(db, downloader)
    rows = db.scalars(
        select(AppRecord).where(AppRecord.enabled.is_(True)).order_by(AppRecord.name)
    ).all()
    return page(
        [catalog_app(db, r) for r in rows if not q or q.casefold() in r.name.casefold()],
        page_number,
        page_size,
    )


@router.get("/catalog/apps/{id}", response_model=dto.CatalogApp, operation_id="get_catalog_app")
def get_catalog_app(id: UUID, db: DB, downloader: Downloader):
    verify_download_context(db, downloader)
    app = must_get(db, AppRecord, id)
    if not app.enabled:
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "资源不存在或不可访问")
    return catalog_app(db, app)


@router.get(
    "/catalog/debug-entries",
    response_model=dto.CatalogEntryPage,
    operation_id="list_catalog_debug_entries",
)
def catalog_entries(
    request: Request,
    db: DB,
    downloader: Downloader,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: str | None = None,
    app_id: UUID | None = None,
    platform: str | None = None,
    sort: Literal["source_updated_at", "imported_at"] = "source_updated_at",
):
    verify_download_context(db, downloader)
    rows = db.scalars(
        select(DebugRecord)
        .join(AppRecord, AppRecord.id == DebugRecord.app_id)
        .where(DebugRecord.enabled.is_(True), AppRecord.enabled.is_(True))
        .order_by(DebugRecord.created_at.desc())
    ).all()
    return page(
        [
            catalog_entry(db, r, request.app.state.settings)
            for r in sort_entries(rows, sort)
            if platform_enabled(db.get(AppRecord, r.app_id), r.platform)
            and (not app_id or r.app_id == app_id)
            and (not platform or r.platform == platform)
            and (
                not q
                or q.casefold() in (r.file_name + r.source_tag + (r.version_name or "")).casefold()
            )
        ],
        page_number,
        page_size,
    )


@router.get(
    "/catalog/debug-entries/{id}",
    response_model=dto.CatalogEntry,
    operation_id="get_catalog_debug_entry",
)
def get_catalog_entry(id: UUID, request: Request, db: DB, downloader: Downloader):
    verify_download_context(db, downloader)
    return catalog_entry(db, visible_entry(db, id), request.app.state.settings)


def preparation_dto(row):
    return {
        "entry_id": row.id,
        "state": row.cache_state,
        "downloaded_bytes": row.downloaded_bytes,
        "total_bytes": row.size_bytes,
        "retry_after_seconds": 2 if row.cache_state not in {"ready", "failed"} else 0,
        "error_code": row.cache_error_code,
        "error_message": "文件准备失败，请联系管理员或重试" if row.cache_error_code else None,
    }


@router.get(
    "/catalog/debug-entries/{id}/preparation",
    response_model=dto.Preparation,
    operation_id="get_download_preparation",
)
def preparation(id: UUID, db: DB, downloader: Downloader):
    verify_download_context(db, downloader)
    return preparation_dto(visible_entry(db, id))


@router.post(
    "/catalog/debug-entries/{id}/download-grants",
    response_model=dto.DownloadGrant | dto.Preparation,
    operation_id="create_download_grant",
)
def grant(
    id: UUID,
    request: Request,
    response: Response,
    db: DB,
    downloader: Downloader,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    verify_download_context(db, downloader)
    row = visible_entry(db, id)
    settings = request.app.state.settings
    key, previous = idem_begin(db, f"grant:{downloader.session.id}:{id}", idempotency_key, {})
    if downloader.user.kind == "feishu":
        state(db, "feishu", locked=True)
    db.refresh(downloader.session)
    if (
        downloader.session.revoked_at
        or downloader.session.expires_at <= utcnow()
        or (
            downloader.user.kind == "feishu"
            and (
                not downloader.session.eligibility_until
                or downloader.session.eligibility_until <= utcnow()
            )
        )
    ):
        raise AppError(403, "ELIGIBILITY_UNVERIFIED", "下载资格已过期，请重新登录")
    verify_download_context(db, downloader)
    ttl = cache_settings(db).data["grant_ttl_seconds"]
    app = db.scalar(
        select(AppRecord)
        .where(AppRecord.id == row.app_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    lock(db, cache_lock_key(row))
    db.refresh(row)
    if not row.enabled or not platform_enabled(app, row.platform):
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "资源不存在或不可访问")
    if previous:
        if "encrypted" in previous.data:
            import json

            result = json.loads(
                SecretBox(settings).decrypt(previous.data["encrypted"], scope="download-grant")
            )
            from datetime import datetime

            if datetime.fromisoformat(result["expires_at"]) <= utcnow():
                raise AppError(410, "DOWNLOAD_EXPIRED", "临时链接已过期，请重新获取")
            return result
        response.status_code = 202
        return previous.data
    lock(db, cache_lock_key(row))
    db.refresh(row)
    path = cache_path(settings, row)
    if row.persistent_package_id:
        import json

        from app.domains.library.models import PackageRecord
        from app.domains.storage.service import cloud_grant

        package = must_get(db, PackageRecord, row.persistent_package_id)
        if package.state != "ready" or not package.storage_location_id:
            raise AppError(503, "PACKAGE_NOT_READY", "私有原件暂时不可用")
        result = dict(
            download_url=cloud_grant(db, settings, package),
            expires_at=(utcnow() + timedelta(seconds=300)).isoformat(),
            file_name=row.file_name,
            size_bytes=package.size_bytes,
            sha256=package.sha256,
        )
        idem_save(
            db,
            key,
            {},
            {"encrypted": SecretBox(settings).encrypt(json.dumps(result), scope="download-grant")},
        )
        record_audit(
            db,
            action="download.grant",
            resource_type="debug_entry",
            resource_id=str(id),
            actor_kind="feishu" if downloader.user.kind == "feishu" else "admin",
            actor_id=str(downloader.user.id),
            request_id=request.state.request_id,
            summary="签发私有云存储下载授权；旧本机链接保持原有效期",
        )
    elif row.cache_state != "ready" or not path.is_file() or path.is_symlink():
        if row.cache_state == "ready":
            mark_cache_missing(db, row)
        ensure_cache(db, row)
        result = preparation_dto(row)
        idem_save(db, key, {}, result)
        response.status_code = 202
    else:
        expires = utcnow() + timedelta(seconds=ttl)
        raw = secrets.token_urlsafe(32)
        db.add(GrantRecord(token_hash=token_hash(raw), entry_id=id, expires_at=expires))
        touch_cache(db, row)
        result = {
            "download_url": settings.site_url + "/api/v1/downloads/" + raw,
            "expires_at": expires.isoformat(),
            "file_name": row.file_name,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
        }
        import json

        # Idempotent replay is encrypted; the grant lookup stores only a token hash.
        idem_save(
            db,
            key,
            {},
            {"encrypted": SecretBox(settings).encrypt(json.dumps(result), scope="download-grant")},
        )
        record_audit(
            db,
            action="download.grant",
            resource_type="debug_entry",
            resource_id=str(id),
            actor_kind="feishu" if downloader.user.kind == "feishu" else "admin",
            actor_id=str(downloader.user.id),
            request_id=request.state.request_id,
            summary="签发临时下载授权",
        )
    db.commit()
    return result


def parse_range(value, size):
    if not value:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or size == 0 or not any(match.groups()):
        raise ValueError("invalid range")
    left, right = match.groups()
    if not left:
        suffix = int(right)
        if suffix <= 0:
            raise ValueError("invalid suffix")
        return max(0, size - suffix), size - 1, True
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start >= size or start > end:
        raise ValueError("out of range")
    return start, end, True


def download_response(opaque_token, request, db, head=False):
    settings = request.app.state.settings
    grant = db.get(GrantRecord, token_hash(opaque_token)) if len(opaque_token) <= 200 else None

    def failure(status, code, message, headers=None):
        if head:
            return Response(status_code=status, headers=headers)
        return error_response(request, status, code, message, headers=headers)

    if not grant:
        return failure(404, "RESOURCE_NOT_AVAILABLE", "下载链接无效")
    if grant.expires_at <= utcnow():
        return failure(410, "DOWNLOAD_EXPIRED", "下载链接已过期")
    row = db.get(DebugRecord, grant.entry_id)
    lock(db, cache_lock_key(row))
    path = cache_path(settings, row)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size != row.size_bytes
            or row.cache_state != "ready"
        ):
            os.close(descriptor)
            return failure(409, "CACHE_NOT_READY", "文件缓存不可用")
    except OSError:
        return failure(409, "CACHE_NOT_READY", "文件缓存不可用")
    file = os.fdopen(descriptor, "rb")
    try:
        start, end, partial = parse_range(
            None if head else request.headers.get("range"), row.size_bytes
        )
    except ValueError:
        file.close()
        return failure(
            416,
            "RANGE_NOT_SATISFIABLE",
            "请求范围无效",
            {"Content-Range": f"bytes */{row.size_bytes}"},
        )
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Type": "application/octet-stream",
        "Content-Disposition": "attachment; filename=package; filename*=UTF-8''"
        + quote(row.file_name, safe=""),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{row.size_bytes}"
    if head:
        file.close()
        db.commit()
        return Response(status_code=200, headers=headers)
    lease = TransferLease(id=uuid4(), entry_id=row.id, expires_at=utcnow() + timedelta(seconds=120))
    db.add(lease)
    touch_cache(db, row)
    db.commit()
    lease_id = lease.id
    engine = request.app.state.engine

    def renew_lease(stopped):
        while not stopped.wait(30):
            try:
                with Session(engine) as stream_db:
                    active = stream_db.get(TransferLease, lease_id)
                    if active:
                        active.expires_at = utcnow() + timedelta(seconds=120)
                        stream_db.commit()
            except Exception:
                continue

    def stream():
        stopped = threading.Event()
        renewer = threading.Thread(target=renew_lease, args=(stopped,), daemon=True)
        renewer.start()
        try:
            file.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            stopped.set()
            file.close()
            with Session(engine) as stream_db:
                active = stream_db.get(TransferLease, lease_id)
                if active:
                    stream_db.delete(active)
                    stream_db.commit()

    return StreamingResponse(stream(), status_code=206 if partial else 200, headers=headers)


@router.get("/downloads/{opaque_token}", operation_id="get_download")
def download(opaque_token: str, request: Request, db: DB):
    return download_response(opaque_token, request, db)


@router.head("/downloads/{opaque_token}", operation_id="head_download")
def download_head(opaque_token: str, request: Request, db: DB):
    return download_response(opaque_token, request, db, head=True)
