from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api import contracts as dto
from app.api.dependencies import CSRF, DB, Admin, require_revision
from app.api.library import active_app, audit
from app.core.errors import AppError
from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord
from app.domains.distribution.service import enqueue, must_get, task_accepted
from app.domains.library.models import (
    LibraryGrant,
    PackageRecord,
    PublicationPackage,
    PublicationRecord,
    ReleaseDefault,
    UploadRecord,
)

router = APIRouter(tags=["PackageLibrary"])


def defaults(db, id, platform):
    row = db.get(ReleaseDefault, (id, platform))
    return dict(
        app_id=id,
        platform=platform,
        publication_id=row.publication_id if row else None,
        revision=row.revision if row else 0,
    )


@router.get(
    "/apps/{id}/release-defaults/{platform}",
    response_model=dto.ReleaseDefault,
    operation_id="get_release_default",
)
def get_default(id: UUID, platform: Literal["android", "ios"], db: DB, admin: Admin):
    from app.api.applications import get_app

    get_app(db, id)
    return defaults(db, id, platform)


@router.put(
    "/apps/{id}/release-defaults/{platform}",
    response_model=dto.ReleaseDefault,
    operation_id="set_release_default",
)
def set_default(
    id: UUID,
    platform: Literal["android", "ios"],
    body: dto.ReleaseDefaultUpdate,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    active_app(db, id)
    current = defaults(db, id, platform)
    require_revision(if_match, current["revision"])
    if body.publication_id:
        p = must_get(db, PublicationRecord, body.publication_id)
        if (
            p.app_id != id
            or p.platform != platform
            or p.mode != "release"
            or p.state != "published"
        ):
            raise AppError(409, "DEFAULT_RELEASE_INVALID", "请选择本应用、本平台已发布的 Release")
    row = db.get(ReleaseDefault, (id, platform))
    if row is None:
        row = ReleaseDefault(app_id=id, platform=platform, revision=0)
        db.add(row)
    row.publication_id, row.revision = body.publication_id, row.revision + 1
    audit(db, request, admin, "release.default", id)
    db.commit()
    return defaults(db, id, platform)


def deletion_impact(db, package):
    blockers = []
    retained = package.created_at + timedelta(hours=24)
    if retained > utcnow():
        blockers.append("新入库文件至少保留 24 小时")
    if db.scalar(
        select(PublicationPackage.publication_id)
        .where(PublicationPackage.package_id == package.id)
        .limit(1)
    ):
        blockers.append("仍有发布或历史发布引用，不能删除")
    if db.scalar(
        select(DebugRecord.id).where(DebugRecord.persistent_package_id == package.id).limit(1)
    ):
        blockers.append("仍有旧 Debug 固定页面引用，不能删除")
    if db.scalar(
        select(LibraryGrant.token_hash)
        .where(
            LibraryGrant.package_id == package.id,
            LibraryGrant.expires_at > utcnow() - timedelta(minutes=10),
        )
        .limit(1)
    ):
        blockers.append("仍在最近下载授权的保留窗口内，请稍后重试")
    if db.scalar(
        select(UploadRecord.id)
        .where(UploadRecord.app_id == package.app_id, UploadRecord.state == "processing")
        .limit(1)
    ):
        blockers.append("应用仍有入库任务，完成后再删除")
    if package.state == "deleted":
        blockers.append("文件已删除")
    return dict(
        package_id=package.id,
        revision=package.revision,
        can_delete=not blockers,
        retained_until=retained,
        blockers=blockers,
    )


@router.get(
    "/packages/{id}/deletion-impact",
    response_model=dto.PackageDeletionImpact,
    operation_id="package_deletion_impact",
)
def impact(id: UUID, db: DB, admin: Admin):
    return deletion_impact(db, must_get(db, PackageRecord, id))


@router.delete(
    "/packages/{id}",
    response_model=dto.TaskAccepted,
    status_code=202,
    operation_id="delete_package",
)
def delete(
    id: UUID,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    row = must_get(db, PackageRecord, id)
    active_app(db, row.app_id)
    db.refresh(row, with_for_update=True)
    require_revision(if_match, row.revision)
    result = deletion_impact(db, row)
    if result["blockers"]:
        raise AppError(409, "PACKAGE_IN_USE", "；".join(result["blockers"]))
    task = enqueue(
        db,
        "package_delete",
        resource_id=str(id),
        app_id=row.app_id,
        dedupe_key=f"package-delete:{id}",
    )
    row.state, row.revision = "deleting", row.revision + 1
    audit(db, request, admin, "package.delete_requested", id)
    db.commit()
    return task_accepted(task)
