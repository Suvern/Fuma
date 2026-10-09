"""Authenticated upload protocol and immutable private publications."""

import asyncio
import hashlib
import math
import os
import re
import secrets
import shutil
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import AwareDatetime
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.api import contracts as dto
from app.api.app_access import ScopedManager
from app.api.applications import get_app
from app.api.dependencies import (
    CSRF,
    DB,
    optional_context,
    require_downloader,
    require_revision,
)
from app.core.errors import AppError
from app.domains.access.authorization import require_app_permission
from app.domains.applications.models import AppRecord
from app.domains.applications.service import package_ids, platform_enabled, require_platform_enabled
from app.domains.audit.service import record_audit
from app.domains.auth.service import AuthContext, token_hash, utcnow
from app.domains.distribution.feishu import verify_download_context
from app.domains.distribution.service import enqueue, idem_begin, idem_save, lock, must_get, page
from app.domains.library.models import (
    LibraryGrant,
    PackageRecord,
    PublicationPackage,
    PublicationRecord,
    ReleaseDefault,
    UploadRecord,
    VersionRecord,
)

router = APIRouter(tags=["PackageLibrary"])
CHUNK_SIZE = 16 * 1024 * 1024
UPLOAD_BUDGET = 10 * 1024**3


def root(settings):
    return settings.state_dir / "library"


def upload_dir(settings, id):
    return root(settings) / "uploads" / str(UUID(str(id)))


def package_file(settings, id):
    return root(settings) / "packages" / (str(UUID(str(id))) + ".bin")


def audit(db, request, admin, action, id):
    record_audit(
        db,
        action=action,
        resource_type="package_library",
        resource_id=str(id),
        actor_id=str(admin.user.id) if admin and admin.user else None,
        request_id=request.state.request_id,
    )


def active_app(db, id):
    app = get_app(db, id, lock=True)
    if app.archived_at or not app.enabled:
        raise AppError(409, "APP_NOT_READY", "请先恢复并启用应用")
    return app


def validate_scope(db, app, platform, mode, identifier=None):
    require_platform_enabled(app, platform)
    configured = [
        r["identifier"]
        for r in package_ids(db, app.id)
        if r["platform"] == platform and r["mode"] == mode
    ]
    if not configured:
        raise AppError(409, "PACKAGE_ID_UNCONFIGURED", "请先配置对应平台和模式的允许包标识")
    if identifier is not None:

        def norm(value):
            return value.lower() if platform == "ios" else value

        if norm(identifier) not in [norm(x) for x in configured]:
            raise AppError(409, "PACKAGE_ID_MISMATCH", "安装包标识与应用配置不一致")


def upload_dto(row):
    return {name: getattr(row, name) for name in dto.UploadSession.model_fields}


def package_dto(row):
    return {
        name: getattr(row, name)
        for name in dto.PackageInfo.model_fields
        if name not in {"related_uploads", "publication_refs"}
    }


def version_dto(row):
    return {name: getattr(row, name) for name in dto.VersionInfo.model_fields}


def publication_dto(db, row):
    return {
        **{
            name: getattr(row, name)
            for name in dto.PublicationInfo.model_fields
            if name != "package_ids"
        },
        "package_ids": list(
            db.scalars(
                select(PublicationPackage.package_id)
                .where(PublicationPackage.publication_id == row.id)
                .order_by(PublicationPackage.package_id)
            )
        ),
    }


def locked_upload(db, id, *, receiving=False):
    row = must_get(db, UploadRecord, id)
    active_app(db, row.app_id)
    db.refresh(row, with_for_update=True)
    if receiving and (row.state != "receiving" or row.expires_at <= utcnow()):
        raise AppError(409, "UPLOAD_NOT_RECEIVING", "上传已过期、取消或已提交处理，请刷新状态")
    return row


@router.post(
    "/apps/{id}/uploads",
    response_model=dto.UploadSession,
    status_code=201,
    operation_id="create_upload",
)
def create_upload(
    id: UUID,
    body: dto.UploadCreate,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    idempotency_key: Annotated[str, Header()],
):
    app = active_app(db, id)
    validate_scope(db, app, body.platform, body.mode)
    from app.domains.storage.models import StorageLocation
    from app.domains.storage.service import ready_location

    location_id = body.storage_location_id
    if "storage_location_id" not in body.model_fields_set:
        location_id = db.scalar(
            select(StorageLocation.id).where(StorageLocation.is_default.is_(True))
        )
    if location_id:
        ready_location(db, location_id)
    if not re.fullmatch(
        r"[^/\\\x00-\x1f\x7f]{1,255}", body.file_name
    ) or not body.file_name.lower().endswith(".apk" if body.platform == "android" else ".ipa"):
        raise AppError(422, "INVALID_FILE_NAME", "文件名或扩展名不符合目标平台")
    key, previous = idem_begin(
        db, f"upload:{admin.user.id}:{id}", idempotency_key, body.model_dump(mode="json")
    )
    if previous:
        return upload_dto(must_get(db, UploadRecord, UUID(previous.data["id"])))
    lock(db, "library:upload-budget")
    reserved = db.scalar(
        select(func.coalesce(func.sum(UploadRecord.declared_size), 0)).where(
            UploadRecord.state.in_(["receiving", "processing", "failed"])
        )
    )
    count = db.scalar(
        select(func.count())
        .select_from(UploadRecord)
        .where(
            UploadRecord.actor_id == admin.user.id,
            UploadRecord.state.in_(["receiving", "processing"]),
        )
    )
    directory = root(request.app.state.settings)
    directory.mkdir(parents=True, exist_ok=True)
    if count >= 3 or reserved + body.declared_size > UPLOAD_BUDGET:
        raise AppError(
            409, "UPLOAD_QUOTA_EXCEEDED", "最多同时 3 个上传，暂存预算 10 GiB；请取消旧上传后重试"
        )
    if shutil.disk_usage(directory).free < body.declared_size * 3 + 256 * 1024**2:
        raise AppError(409, "UPLOAD_DISK_FULL", "磁盘剩余空间不足以接收和合并安装包")
    now = utcnow()
    row = UploadRecord(
        app_id=id,
        actor_id=admin.user.id,
        **body.model_dump(exclude={"storage_location_id"}),
        storage_location_id=location_id,
        chunk_size=CHUNK_SIZE,
        expected_parts=math.ceil(body.declared_size / CHUNK_SIZE),
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    db.add(row)
    db.flush()
    idem_save(db, key, body.model_dump(mode="json"), {"id": str(row.id)})
    audit(db, request, admin, "upload.create", row.id)
    db.commit()
    return upload_dto(row)


@router.get("/apps/{id}/uploads", response_model=dto.UploadPage, operation_id="list_uploads")
def uploads(
    id: UUID,
    db: DB,
    admin: ScopedManager,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
):
    get_app(db, id)
    rows = db.scalars(
        select(UploadRecord)
        .where(UploadRecord.app_id == id)
        .order_by(UploadRecord.created_at.desc(), UploadRecord.id)
    )
    return page(
        [upload_dto(r) for r in rows if not q or q.casefold() in r.file_name.casefold()],
        page_number,
        page_size,
    )


@router.get("/uploads/{id}", response_model=dto.UploadSession, operation_id="get_upload")
def upload(id: UUID, db: DB, admin: ScopedManager):
    return upload_dto(must_get(db, UploadRecord, id))


@router.put(
    "/uploads/{id}/parts/{part_number}",
    response_model=dto.UploadPart,
    operation_id="put_upload_part",
)
async def upload_part(
    id: UUID,
    part_number: int,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    x_chunk_sha256: Annotated[str, Header()],
):
    # Do not hold a blocking database row lock while awaiting an HTTP body: a
    # concurrent request could otherwise block the event loop needed by this one.
    def snapshot():
        row = must_get(db, UploadRecord, id)
        require_app_permission(db, admin, row.app_id, lock=True)
        row = locked_upload(db, id, receiving=True)
        values = row.expected_parts, row.chunk_size, row.declared_size
        db.rollback()
        return values

    expected_parts, chunk_size, declared_size = await run_in_threadpool(snapshot)
    if not 1 <= part_number <= expected_parts or not re.fullmatch("[a-f0-9]{64}", x_chunk_sha256):
        raise AppError(422, "INVALID_UPLOAD_PART", "分片编号或 SHA-256 不合法")
    expected = min(chunk_size, declared_size - (part_number - 1) * chunk_size)
    directory = upload_dir(request.app.state.settings, id)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (str(uuid4()) + ".tmp")
    digest, size = hashlib.sha256(), 0
    try:
        async with asyncio.timeout(120):
            with temporary.open("xb") as stream:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > expected:
                        raise AppError(413, "UPLOAD_PART_TOO_LARGE", "分片超过声明大小")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        if size != expected or digest.hexdigest() != x_chunk_sha256:
            raise AppError(422, "UPLOAD_PART_MISMATCH", "分片长度或校验和不匹配")
        part = {"part_number": part_number, "size_bytes": size, "sha256": x_chunk_sha256}

        def finalize():
            row = must_get(db, UploadRecord, id)
            require_app_permission(db, admin, row.app_id, lock=True)
            db.info["actor_app_id"] = row.app_id
            row = locked_upload(db, id, receiving=True)
            old = next((p for p in row.parts if p["part_number"] == part_number), None)
            if old and old != part:
                raise AppError(409, "UPLOAD_PART_CONFLICT", "已有分片内容不同，请创建新上传")
            os.replace(temporary, directory / str(part_number))
            row.parts = sorted(
                [p for p in row.parts if p["part_number"] != part_number] + [part],
                key=lambda p: p["part_number"],
            )
            db.commit()

        await run_in_threadpool(finalize)
        return part
    except TimeoutError as exc:
        raise AppError(408, "UPLOAD_TIMEOUT", "分片上传超时，请重试当前分片") from exc
    finally:
        temporary.unlink(missing_ok=True)


@router.delete("/uploads/{id}", response_model=dto.UploadSession, operation_id="cancel_upload")
def cancel_upload(id: UUID, request: Request, db: DB, admin: ScopedManager, csrf: CSRF):
    row = must_get(db, UploadRecord, id)
    get_app(db, row.app_id, lock=True)
    db.refresh(row, with_for_update=True)
    if row.state not in {"receiving", "failed", "expired", "cancelled"}:
        raise AppError(409, "UPLOAD_NOT_CANCELLABLE", "已交给处理任务或已入库，不能取消")
    from app.domains.library.cleanup import cleanup_staging

    try:
        cleanup_staging(db, request.app.state.settings, row)
    except OSError as exc:
        raise AppError(503, "UPLOAD_CLEANUP_FAILED", "暂存文件清理失败，请重试取消") from exc
    row.state, row.parts = "cancelled", []
    audit(db, request, admin, "upload.cancel", id)
    db.commit()
    return upload_dto(row)


def submit_upload(id, request, db, admin, retry):
    row = locked_upload(db, id)
    if row.state in {"processing", "ready"}:
        return upload_dto(row)
    if row.state != ("failed" if retry else "receiving") or row.expires_at <= utcnow():
        raise AppError(409, "UPLOAD_NOT_READY", "上传状态不允许提交，请创建新上传")
    if not row.source_snapshot and (
        len(row.parts) != row.expected_parts
        or sum(p["size_bytes"] for p in row.parts) != row.declared_size
    ):
        raise AppError(409, "UPLOAD_INCOMPLETE", "分片不完整，请继续上传")
    if retry:
        from app.domains.library.cleanup import cleanup_parser_jobs

        cleanup_parser_jobs(db, request.app.state.settings, row)
    task = enqueue(db, "package_ingest", resource_id=str(id), app_id=row.app_id)
    row.state, row.task_id, row.error_message = "processing", task.id, None
    audit(db, request, admin, "upload.submit", id)
    db.commit()
    return upload_dto(row)


@router.post(
    "/uploads/{id}/complete",
    response_model=dto.UploadSession,
    status_code=202,
    operation_id="complete_upload",
)
def complete_upload(id: UUID, request: Request, db: DB, admin: ScopedManager, csrf: CSRF):
    return submit_upload(id, request, db, admin, False)


@router.post(
    "/uploads/{id}/retry",
    response_model=dto.UploadSession,
    status_code=202,
    operation_id="retry_upload",
)
def retry_upload(id: UUID, request: Request, db: DB, admin: ScopedManager, csrf: CSRF):
    return submit_upload(id, request, db, admin, True)


@router.get("/apps/{id}/packages", response_model=dto.PackagePage, operation_id="list_packages")
def packages(
    id: UUID,
    db: DB,
    admin: ScopedManager,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    platform: Literal["android", "ios"] | None = None,
    mode: Literal["debug", "release"] | None = None,
    state: Literal["processing", "ready", "deleting", "deleted"] | None = None,
    source_kind: Literal["upload", "github"] | None = None,
    created_from: AwareDatetime | None = None,
    created_before: AwareDatetime | None = None,
):
    get_app(db, id)
    if created_from and created_before and created_from >= created_before:
        raise AppError(422, "INVALID_TIME_RANGE", "入库起始时间必须早于结束时间")
    rows = db.scalars(
        select(PackageRecord)
        .where(PackageRecord.app_id == id)
        .order_by(PackageRecord.created_at.desc(), PackageRecord.id)
    )
    return page(
        [
            package_dto(r)
            for r in rows
            if (
                not q
                or q.casefold()
                in f"{r.file_name} {r.version_name} {r.package_identifier}".casefold()
            )
            and (not platform or r.platform == platform)
            and (not mode or r.mode == mode)
            and (not state or r.state == state)
            and (not source_kind or r.source_kind == source_kind)
            and (not created_from or r.created_at >= created_from)
            and (not created_before or r.created_at < created_before)
        ],
        page_number,
        page_size,
    )


@router.get("/packages/{id}", response_model=dto.PackageInfo, operation_id="get_package")
def package(id: UUID, db: DB, admin: ScopedManager):
    row = must_get(db, PackageRecord, id)
    return {
        **package_dto(row),
        "related_uploads": [
            upload_dto(upload)
            for upload in db.scalars(
                select(UploadRecord)
                .where(UploadRecord.package_id == id)
                .order_by(UploadRecord.created_at.desc(), UploadRecord.id)
            )
        ],
        "publication_refs": [
            publication_dto(db, publication)
            for publication in db.scalars(
                select(PublicationRecord)
                .join(PublicationPackage)
                .where(PublicationPackage.package_id == id)
                .order_by(PublicationRecord.created_at.desc(), PublicationRecord.id)
            )
        ],
    }


@router.patch("/packages/{id}", response_model=dto.PackageInfo, operation_id="update_package_notes")
def notes(
    id: UUID,
    body: dto.PackageNotes,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    row = must_get(db, PackageRecord, id)
    get_app(db, row.app_id, lock=True)
    db.refresh(row, with_for_update=True)
    require_revision(if_match, row.revision)
    row.internal_notes, row.revision = body.internal_notes, row.revision + 1
    audit(db, request, admin, "package.notes", id)
    db.commit()
    return package_dto(row)


@router.post(
    "/apps/{id}/versions",
    response_model=dto.VersionInfo,
    status_code=201,
    operation_id="create_version",
)
def create_version(
    id: UUID,
    body: dto.VersionCreate,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    active_app(db, id)
    key = None
    if idempotency_key:
        key, previous = idem_begin(
            db, f"version:{admin.user.id}:{id}", idempotency_key, body.model_dump(mode="json")
        )
        if previous:
            return version_dto(must_get(db, VersionRecord, UUID(previous.data["id"])))
    if not body.display_name.strip():
        raise AppError(422, "INVALID_VERSION_NAME", "版本名称不能为空")
    row = VersionRecord(app_id=id, **body.model_dump(), created_at=utcnow())
    db.add(row)
    db.flush()
    if key:
        idem_save(db, key, body.model_dump(mode="json"), {"id": str(row.id)})
    audit(db, request, admin, "version.create", row.id)
    db.commit()
    return version_dto(row)


@router.get("/apps/{id}/versions", response_model=dto.VersionPage, operation_id="list_versions")
def versions(
    id: UUID,
    db: DB,
    admin: ScopedManager,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
):
    get_app(db, id)
    rows = db.scalars(
        select(VersionRecord)
        .where(VersionRecord.app_id == id)
        .order_by(VersionRecord.created_at.desc(), VersionRecord.id)
    )
    return page(
        [version_dto(r) for r in rows if not q or q.casefold() in r.display_name.casefold()],
        page_number,
        page_size,
    )


@router.get("/versions/{id}", response_model=dto.VersionInfo, operation_id="get_version")
def version(id: UUID, db: DB, admin: ScopedManager):
    return version_dto(must_get(db, VersionRecord, id))


@router.patch("/versions/{id}", response_model=dto.VersionInfo, operation_id="update_version")
def update_version(
    id: UUID,
    body: dto.VersionCreate,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    row = must_get(db, VersionRecord, id)
    active_app(db, row.app_id)
    db.refresh(row, with_for_update=True)
    require_revision(if_match, row.revision)
    if not body.display_name.strip():
        raise AppError(422, "INVALID_VERSION_NAME", "版本名称不能为空")
    if body.mode != row.mode:
        raise AppError(409, "VERSION_MODE_IMMUTABLE", "版本模式不能修改")
    row.display_name, row.release_notes, row.revision = (
        body.display_name,
        body.release_notes,
        row.revision + 1,
    )
    audit(db, request, admin, "version.update", id)
    db.commit()
    return version_dto(row)


@router.post(
    "/versions/{id}/publications",
    response_model=dto.PublicationInfo,
    status_code=201,
    operation_id="create_publication",
)
def create_publication(
    id: UUID,
    body: dto.PublicationCreate,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    version = must_get(db, VersionRecord, id)
    app = active_app(db, version.app_id)
    key = None
    if idempotency_key:
        key, previous = idem_begin(
            db, f"publication:{admin.user.id}:{id}", idempotency_key, body.model_dump(mode="json")
        )
        if previous:
            return publication_dto(db, must_get(db, PublicationRecord, UUID(previous.data["id"])))
    if body.public_storage_id:
        from app.domains.storage.service import ready_location

        if version.mode != "release":
            raise AppError(409, "PUBLIC_DEBUG_FORBIDDEN", "Debug 原件和发布必须保持私有")
        ready_location(db, body.public_storage_id, "public")
    if len(set(body.package_ids)) != len(body.package_ids):
        raise AppError(422, "DUPLICATE_PACKAGE", "文件不能重复")
    for package_id in body.package_ids:
        package = must_get(db, PackageRecord, package_id)
        if (
            package.app_id != app.id
            or package.platform != body.platform
            or package.mode != version.mode
            or package.state != "ready"
        ):
            raise AppError(
                409, "PACKAGE_SCOPE_MISMATCH", "文件必须属于同应用、平台和模式，且入库完成"
            )
        validate_scope(db, app, package.platform, package.mode, package.package_identifier)
    row = PublicationRecord(
        app_id=app.id,
        version_id=id,
        platform=body.platform,
        mode=version.mode,
        created_at=utcnow(),
        public_storage_id=body.public_storage_id,
    )
    db.add(row)
    db.flush()
    db.add_all(PublicationPackage(publication_id=row.id, package_id=p) for p in body.package_ids)
    if key:
        idem_save(db, key, body.model_dump(mode="json"), {"id": str(row.id)})
    audit(db, request, admin, "publication.create", row.id)
    db.commit()
    return publication_dto(db, row)


@router.get(
    "/versions/{id}/publications",
    response_model=dto.PublicationPage,
    operation_id="list_publications",
)
def publications(
    id: UUID,
    db: DB,
    admin: ScopedManager,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
):
    must_get(db, VersionRecord, id)
    rows = db.scalars(
        select(PublicationRecord)
        .where(PublicationRecord.version_id == id)
        .order_by(PublicationRecord.created_at.desc(), PublicationRecord.id)
    )
    return page(
        [publication_dto(db, r) for r in rows if not q or q in r.platform], page_number, page_size
    )


@router.get(
    "/publications/{id}", response_model=dto.PublicationInfo, operation_id="get_publication"
)
def publication(id: UUID, db: DB, admin: ScopedManager):
    return publication_dto(db, must_get(db, PublicationRecord, id))


def transition(id, action, request, db, admin, revision):
    row = must_get(db, PublicationRecord, id)
    app = get_app(db, row.app_id, lock=True)
    db.refresh(row, with_for_update=True)
    require_revision(revision, row.revision)
    if row.access_state in {"publishing", "reclaiming", "reclaim_failed"}:
        raise AppError(
            409, "PUBLICATION_ACCESS_PENDING", "公开访问变更尚未完成，请查看或重试访问任务"
        )
    allowed = {
        "publish": ({"draft", "unpublished"}, "published"),
        "unpublish": ({"published"}, "unpublished"),
        "archive": ({"draft", "unpublished"}, "archived"),
        "restore": ({"archived"}, "draft"),
    }
    before, after = allowed[action]
    if row.state not in before:
        raise AppError(409, "PUBLICATION_STATE_CONFLICT", "发布状态已变化，请刷新后重试")
    if action in {"publish", "restore"} and (app.archived_at or not app.enabled):
        raise AppError(409, "APP_NOT_READY", "请先恢复并启用应用")
    if action == "publish":
        items = publication_dto(db, row)["package_ids"]
        if not items:
            raise AppError(409, "PUBLICATION_EMPTY", "发布必须包含安装包")
        for id in items:
            package = must_get(db, PackageRecord, id)
            validate_scope(db, app, row.platform, row.mode, package.package_identifier)
            if package.state != "ready" or (
                not package.storage_location_id
                and not package_file(request.app.state.settings, id).is_file()
            ):
                raise AppError(409, "PACKAGE_NOT_READY", "文件不可用，不能发布")
        row.file_set_frozen = True
        row.published_at = utcnow()
    row.state, row.revision = after, row.revision + 1
    if action == "unpublish":
        default = db.get(ReleaseDefault, (row.app_id, row.platform))
        if default and default.publication_id == row.id:
            default.publication_id, default.revision = None, default.revision + 1
    if row.public_storage_id and action in {"publish", "unpublish"}:
        from app.domains.storage.service import ready_location

        if action == "publish":
            ready_location(db, row.public_storage_id, "public")
        task = enqueue(
            db,
            "publication_access",
            resource_id=str(row.id),
            app_id=row.app_id,
            payload={"action": "publish" if action == "publish" else "reclaim"},
        )
        row.access_task_id, row.access_error = task.id, None
        row.access_state = "publishing" if action == "publish" else "reclaiming"
        row.state = "draft" if action == "publish" else "unpublished"
    audit(db, request, admin, "publication." + action, row.id)
    db.commit()
    return publication_dto(db, row)


@router.post(
    "/publications/{id}/publish",
    response_model=dto.PublicationInfo,
    operation_id="publish_publication",
)
def publish(
    id: UUID,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    return transition(id, "publish", request, db, admin, if_match)


@router.post(
    "/publications/{id}/unpublish",
    response_model=dto.PublicationInfo,
    operation_id="unpublish_publication",
)
def unpublish(
    id: UUID,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    return transition(id, "unpublish", request, db, admin, if_match)


@router.post(
    "/publications/{id}/archive",
    response_model=dto.PublicationInfo,
    operation_id="archive_publication",
)
def archive(
    id: UUID,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    return transition(id, "archive", request, db, admin, if_match)


@router.post(
    "/publications/{id}/restore",
    response_model=dto.PublicationInfo,
    operation_id="restore_publication",
)
def restore(
    id: UUID,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    return transition(id, "restore", request, db, admin, if_match)


@router.post(
    "/publications/{id}/retry-access",
    response_model=dto.PublicationInfo,
    operation_id="retry_publication_access",
)
def retry_access(
    id: UUID,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    row = must_get(db, PublicationRecord, id)
    get_app(db, row.app_id, lock=True)
    db.refresh(row, with_for_update=True)
    require_revision(if_match, row.revision)
    if row.access_state != "reclaim_failed":
        raise AppError(
            409, "PUBLICATION_STATE_CONFLICT", "仅失败的访问收回可重试；发布失败请重新确认发布"
        )
    task = enqueue(
        db,
        "publication_access",
        resource_id=str(id),
        app_id=row.app_id,
        payload={"action": "reclaim"},
    )
    row.access_state, row.access_task_id, row.access_error = "reclaiming", task.id, None
    row.revision += 1
    audit(db, request, admin, "publication.reclaim_retry", id)
    db.commit()
    return publication_dto(db, row)


Downloader = Annotated[AuthContext, Depends(require_downloader)]
CatalogContext = Annotated[AuthContext | None, Depends(optional_context)]


def authorize_catalog(db, context, row=None):
    if row and row.public_storage_id and row.access_state == "public":
        return
    if context is None or context.user is None:
        raise AppError(401, "AUTHENTICATION_REQUIRED", "请登录后查看受限版本")
    require_downloader(context)
    verify_download_context(db, context)


def published_dto(db, row):
    version = db.get(VersionRecord, row.version_id)
    app = db.get(AppRecord, row.app_id)
    default = db.get(ReleaseDefault, (row.app_id, row.platform))
    files = list(
        db.scalars(
            select(PackageRecord)
            .join(PublicationPackage, PublicationPackage.package_id == PackageRecord.id)
            .where(PublicationPackage.publication_id == row.id)
            .order_by(PackageRecord.id)
        )
    )
    return dict(
        id=row.id,
        app_id=app.id,
        app_name=app.name,
        version_name=version.display_name,
        release_notes=version.release_notes,
        platform=row.platform,
        mode=row.mode,
        published_at=row.published_at,
        is_default=bool(default and default.publication_id == row.id),
        files=[
            {field: getattr(package, field) for field in dto.PublishedFile.model_fields}
            for package in files
        ],
    )


def visible_publication(db, id, *, locked=False):
    row = must_get(db, PublicationRecord, id)
    app = get_app(db, row.app_id, lock=locked)
    if locked:
        db.refresh(row, with_for_update=True)
    if (
        row.state != "published"
        or not app.enabled
        or app.archived_at
        or not platform_enabled(app, row.platform)
    ):
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "资源不存在或不可访问")
    return row


@router.get(
    "/catalog/publications",
    response_model=dto.PublishedReleasePage,
    operation_id="catalog_publications",
)
def catalog_publications(
    db: DB,
    downloader: CatalogContext,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    app_name: str | None = Query(None, max_length=100),
    version_name: str | None = Query(None, max_length=100),
    platform: Literal["android", "ios"] | None = None,
    mode: Literal["debug", "release"] | None = None,
):
    try:
        authorize_catalog(db, downloader)
        private_allowed = True
    except AppError:
        private_allowed = False
    rows = db.scalars(
        select(PublicationRecord)
        .join(AppRecord)
        .where(
            PublicationRecord.state == "published",
            AppRecord.enabled.is_(True),
            AppRecord.archived_at.is_(None),
        )
        .order_by(PublicationRecord.published_at.desc(), PublicationRecord.id)
    ).all()
    rows = [
        row
        for row in rows
        if (not platform or row.platform == platform)
        and (not mode or row.mode == mode)
        and platform_enabled(db.get(AppRecord, row.app_id), row.platform)
    ]
    items = [
        published_dto(db, row)
        for row in rows
        if private_allowed or (row.public_storage_id and row.access_state == "public")
    ]
    items.sort(key=lambda item: not item["is_default"])
    return page(
        [
            item
            for item in items
            if (not q or q.casefold() in (item["app_name"] + " " + item["version_name"]).casefold())
            and (not app_name or app_name.casefold() in item["app_name"].casefold())
            and (not version_name or version_name.casefold() in item["version_name"].casefold())
        ],
        page_number,
        page_size,
    )


@router.get(
    "/catalog/publications/{id}",
    response_model=dto.PublishedRelease,
    operation_id="catalog_publication",
)
def catalog_publication(id: UUID, db: DB, downloader: CatalogContext):
    row = must_get(db, PublicationRecord, id)
    authorize_catalog(db, downloader, row)
    return published_dto(db, visible_publication(db, id))


@router.post(
    "/catalog/publications/{id}/grants",
    response_model=dto.PublicationDownloadGrant,
    operation_id="grant_publication_download",
)
def grant_publication(
    id: UUID,
    body: dto.PublicationDownloadRequest,
    request: Request,
    db: DB,
    downloader: CatalogContext,
    csrf: CSRF,
):
    row = must_get(db, PublicationRecord, id)
    authorize_catalog(db, downloader, row)
    private = not (row.public_storage_id and row.access_state == "public")
    if private and downloader and downloader.user.kind == "feishu":
        from app.domains.distribution.service import state

        # Match the existing Debug grant lock order: Feishu config, then App.
        state(db, "feishu", locked=True)
    row = visible_publication(db, id, locked=True)
    if private:
        if downloader and downloader.user and downloader.user.kind == "feishu":
            db.refresh(downloader.session)
            if (
                downloader.session.revoked_at
                or downloader.session.expires_at <= utcnow()
                or not downloader.session.eligibility_until
                or downloader.session.eligibility_until <= utcnow()
            ):
                raise AppError(403, "ELIGIBILITY_UNVERIFIED", "下载资格已过期，请重新登录")
        authorize_catalog(db, downloader, row)
    if not db.get(PublicationPackage, (id, body.package_id)):
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "资源不存在或不可访问")
    package = must_get(db, PackageRecord, body.package_id)
    if package.state != "ready" or (
        not package.storage_location_id
        and not row.public_storage_id
        and not package_file(request.app.state.settings, package.id).is_file()
    ):
        raise AppError(503, "PACKAGE_NOT_READY", "安装包文件暂时不可用")
    raw = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(seconds=300)
    url = request.app.state.settings.site_url + "/api/v1/library-downloads/" + raw
    if row.public_storage_id:
        from app.domains.storage.models import StorageLocation, StoredObject
        from app.domains.storage.service import adapter

        artifact = db.scalar(
            select(StoredObject).where(
                StoredObject.publication_id == id,
                StoredObject.package_id == package.id,
                StoredObject.state == "ready",
            )
        )
        if not artifact:
            raise AppError(503, "PACKAGE_NOT_READY", "公开副本暂时不可用")
        client = adapter(
            request.app.state.settings, must_get(db, StorageLocation, artifact.location_id)
        )
        client.verify(artifact.object_key, package.size_bytes, package.sha256, public=True)
        url, expires = client.url(artifact.object_key), None
    elif package.storage_location_id:
        from app.domains.storage.service import cloud_grant

        url = cloud_grant(db, request.app.state.settings, package)
    db.add(
        LibraryGrant(
            token_hash=token_hash(raw),
            publication_id=id,
            package_id=package.id,
            expires_at=expires or utcnow(),
        )
    )
    audit(db, request, downloader, "publication.download_grant", id)
    db.commit()
    return dict(
        url=url,
        expires_at=expires,
    )


@router.head("/library-downloads/{token}", operation_id="head_publication_file")
@router.get("/library-downloads/{token}", operation_id="download_publication_file")
def download_publication_file(token: str, request: Request, db: DB):
    from app.domains.distribution.statistics import ObservedFileResponse

    row = db.get(LibraryGrant, token_hash(token)) if len(token) <= 100 else None
    if not row or row.expires_at <= utcnow():
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "链接无效或已过期")
    package = db.get(PackageRecord, row.package_id)
    path = package_file(request.app.state.settings, row.package_id)
    if not package or not path.is_file():
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "安装包不可用")
    file_name, app_id = package.file_name, package.app_id
    # Release the request's database connection before streaming a large file.
    db.commit()
    return ObservedFileResponse(
        path,
        statistics_engine=request.app.state.engine,
        statistics_app_id=app_id,
        filename=file_name,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"},
    )
