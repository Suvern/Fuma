from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api import contracts as dto
from app.api.dependencies import CSRF, DB, Admin
from app.api.library import active_app, audit, create_upload, upload_dto
from app.core.errors import AppError
from app.domains.distribution.models import DebugRecord
from app.domains.distribution.service import enqueue, idem_begin, idem_save, must_get
from app.domains.github.models import GithubRepositorySync
from app.domains.library.models import UploadRecord, VersionRecord
from app.domains.storage.service import ready_location

router = APIRouter(tags=["PackageLibrary"])


def schedule_import(id, body, request, db, admin, csrf, key, legacy=None):
    app = active_app(db, id)
    if not app.repository:
        raise AppError(409, "REPOSITORY_NOT_BOUND", "请先关联 GitHub 仓库")
    snapshot = db.get(GithubRepositorySync, id)
    release = next(
        (r for r in (snapshot.releases if snapshot else []) if r["id"] == body.release_id), None
    )
    asset = next(
        (a for a in (release.get("assets", []) if release else []) if a["id"] == body.asset_id),
        None,
    )
    if not release or release["draft"] or not asset or not asset["supported"]:
        raise AppError(
            409, "SOURCE_NOT_AVAILABLE", "来源不存在、仍是草稿或尚未完成同步；请刷新 Release 后重试"
        )
    if legacy and (
        asset["name"] != legacy.file_name
        or asset["size_bytes"] != legacy.size_bytes
        or asset["updated_at"] != legacy.source["asset_updated_at"]
        or asset.get("digest") != legacy.source.get("digest")
    ):
        raise AppError(409, "SOURCE_CHANGED", "旧条目来源快照与当前附件不一致，不能原位迁移")
    if body.version_id:
        version = must_get(db, VersionRecord, body.version_id)
        if version.app_id != id or version.mode != body.mode:
            raise AppError(409, "VERSION_SCOPE_MISMATCH", "目标版本须属于同应用和同模式")
    payload = {**body.model_dump(mode="json"), "legacy": str(legacy.id) if legacy else None}
    intent, previous = idem_begin(db, f"package-import:{id}", key, payload)
    if previous:
        return upload_dto(must_get(db, UploadRecord, UUID(previous.data["id"])))
    creation = {
        "file_name": asset["name"],
        "declared_size": asset["size_bytes"],
        "platform": asset["platform"],
        "mode": body.mode,
    }
    if "storage_location_id" in body.model_fields_set:
        creation["storage_location_id"] = body.storage_location_id
    # Reuse the same budget, safe names and session idempotency checks as manual upload.
    created = create_upload(id, dto.UploadCreate(**creation), request, db, admin, csrf, key)
    row = must_get(db, UploadRecord, created["id"])
    active_app(db, id)
    db.refresh(row, with_for_update=True)
    if row.source_snapshot:
        return upload_dto(row)
    row.source_snapshot = {
        "repository": dict(app.repository),
        "release_id": release["id"],
        "tag": release["tag_name"],
        "asset": asset,
        "version_id": str(body.version_id) if body.version_id else None,
        "legacy_entry_id": str(legacy.id) if legacy else None,
    }
    task = enqueue(db, "package_ingest", resource_id=str(row.id), app_id=id)
    row.task_id, row.state = task.id, "processing"
    idem_save(db, intent, payload, {"id": str(row.id)})
    audit(db, request, admin, "package.github_import", row.id)
    db.commit()
    return upload_dto(row)


@router.post(
    "/apps/{id}/package-imports",
    response_model=dto.UploadSession,
    status_code=202,
    operation_id="import_package",
)
def import_package(
    id: UUID,
    body: dto.PackageImport,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    idempotency_key: Annotated[str, Header()],
):
    return schedule_import(id, body, request, db, admin, csrf, idempotency_key)


@router.post(
    "/debug-entries/{id}/persist",
    response_model=dto.UploadSession,
    status_code=202,
    operation_id="persist_legacy_package",
)
def persist_legacy(
    id: UUID,
    body: dto.LegacyPersistence,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    idempotency_key: Annotated[str, Header()],
):
    entry = must_get(db, DebugRecord, id)
    app = active_app(db, entry.app_id)
    if entry.persistent_package_id:
        raise AppError(409, "ALREADY_PERSISTED", "该条目已迁入私有存储")
    if (
        not app.repository
        or str(entry.connector_id) != app.repository["connector_id"]
        or entry.source["repository_id"] != app.repository["repository_id"]
    ):
        raise AppError(409, "SOURCE_CHANGED", "条目来源与当前关联不一致，请恢复来源配置后迁移")
    active = db.scalar(
        select(UploadRecord.id).where(
            UploadRecord.app_id == app.id, UploadRecord.state == "processing"
        )
    )
    if active:
        # Serialize legacy migrations to avoid two concurrent source switches.
        for upload in db.scalars(
            select(UploadRecord).where(
                UploadRecord.app_id == app.id, UploadRecord.state == "processing"
            )
        ):
            if upload.source_snapshot and upload.source_snapshot.get("legacy_entry_id") == str(id):
                return upload_dto(upload)
    ready_location(db, body.storage_location_id)
    return schedule_import(
        app.id,
        dto.PackageImport(
            release_id=entry.source["release_id"],
            asset_id=entry.source["asset_id"],
            mode="debug",
            storage_location_id=body.storage_location_id,
        ),
        request,
        db,
        admin,
        csrf,
        idempotency_key,
        entry,
    )
