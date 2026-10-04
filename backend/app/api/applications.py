import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

from app.api.contracts import App, AppArchiveImpact, AppCreate, AppPage, AppUpdate
from app.api.dependencies import DB, require_admin, require_csrf, require_revision
from app.core.errors import AppError
from app.domains.applications.models import AllowedPackageIdRecord, AppCreation, AppRecord
from app.domains.applications.service import (
    archive_impact,
    check_platform_pause,
    check_platform_removal,
    normalize_package_ids,
    package_ids,
    replace_package_ids,
    validate_disabled_platforms,
    validate_icon,
)
from app.domains.audit.service import record_audit
from app.domains.auth.service import AuthContext, utcnow
from app.domains.library.models import PackageRecord, PublicationRecord
from app.infrastructure.database import Base

router = APIRouter(prefix="/apps", tags=["apps"], dependencies=[Depends(require_admin)])
Admin = Annotated[AuthContext, Depends(require_admin)]


def app_dto(db, app: AppRecord) -> App:
    count = 0
    table = Base.metadata.tables.get("debug_entries")
    if table is not None:
        count = db.scalar(select(func.count()).select_from(table).where(table.c.app_id == app.id))
    return App(
        id=app.id,
        created_at=app.created_at,
        updated_at=app.updated_at,
        revision=app.revision,
        name=app.name,
        public_slug=app.public_slug,
        description=app.description,
        platforms=app.platforms,
        disabled_platforms=app.disabled_platforms,
        icon_data=app.icon_data,
        package_count=db.scalar(
            select(func.count())
            .select_from(PackageRecord)
            .where(PackageRecord.app_id == app.id, PackageRecord.state != "deleted")
        ),
        publication_count=db.scalar(
            select(func.count())
            .select_from(PublicationRecord)
            .where(PublicationRecord.app_id == app.id)
        ),
        enabled=app.enabled,
        archived_at=app.archived_at,
        repository=app.repository,
        debug_entry_count=count,
        allowed_package_ids=package_ids(db, app.id),
    )


def get_app(db, id: UUID, *, lock=False) -> AppRecord:
    stmt = select(AppRecord).where(AppRecord.id == id)
    app = db.scalar(
        stmt.with_for_update().execution_options(populate_existing=True) if lock else stmt
    )
    if app is None:
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "App 不存在")
    return app


def audit(db, request, context, action, app):
    record_audit(
        db,
        action=action,
        resource_type="app",
        resource_id=str(app.id),
        actor_id=str(context.user.id),
        request_id=request.state.request_id,
    )


def etag(response, app):
    response.headers["ETag"] = f'"{app.revision}"'


@router.get("", response_model=AppPage, operation_id="list_apps")
def list_apps(
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    platform: Literal["android", "ios"] | None = None,
    enabled: bool | None = None,
    archived: bool | None = None,
):
    stmt = select(AppRecord)
    if q:
        identifiers = (
            select(AllowedPackageIdRecord.app_id)
            .where(
                AllowedPackageIdRecord.app_id == AppRecord.id,
                AllowedPackageIdRecord.identifier.icontains(q, autoescape=True),
            )
            .exists()
        )
        stmt = stmt.where(or_(AppRecord.name.icontains(q, autoescape=True), identifiers))
    if platform:
        stmt = stmt.where(cast(AppRecord.platforms, JSONB).contains([platform]))
    if enabled is not None:
        stmt = stmt.where(AppRecord.enabled.is_(enabled))
    if archived is not None:
        stmt = stmt.where(
            AppRecord.archived_at.is_not(None) if archived else AppRecord.archived_at.is_(None)
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(AppRecord.enabled.desc(), AppRecord.updated_at.desc(), AppRecord.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return AppPage(
        items=[app_dto(db, app) for app in rows], page=page, page_size=page_size, total=total
    )


@router.post(
    "",
    response_model=App,
    status_code=201,
    operation_id="create_apps",
    dependencies=[Depends(require_csrf)],
)
def create_app(
    body: AppCreate,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    idempotency_key: Annotated[UUID, Header()],
):
    if not body.name.strip() or len(set(body.platforms)) != len(body.platforms):
        raise AppError(422, "VALIDATION_ERROR", "App 名称和平台不合法")
    if "allowed_package_ids" in body.model_fields_set and body.allowed_package_ids is None:
        raise AppError(422, "VALIDATION_ERROR", "包标识配置不能为空值，请使用空数组或省略字段")
    key = str(context.user.id) + ":" + str(idempotency_key)
    payload = body.model_dump()
    if body.allowed_package_ids is None:
        # Preserve M1 request hashes across upgrades when the new field is omitted.
        payload.pop("allowed_package_ids")
    # Preserve request hashes for clients that predate these optional fields.
    for field in ("icon_data", "disabled_platforms"):
        if field not in body.model_fields_set:
            payload.pop(field, None)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int(hashlib.sha256(key.encode()).hexdigest()[:15], 16)},
    )
    previous = db.get(AppCreation, key)
    if previous:
        if previous.body_hash != digest:
            raise AppError(409, "IDEMPOTENCY_CONFLICT", "同一请求标识不能提交不同内容")
        app = get_app(db, previous.app_id)
        etag(response, app)
        return app_dto(db, app)
    now = utcnow()
    identifiers = normalize_package_ids(
        [item.model_dump() for item in body.allowed_package_ids or []], body.platforms
    )
    app = AppRecord(
        name=body.name.strip(),
        public_slug=body.public_slug,
        description=body.description or "",
        platforms=body.platforms,
        disabled_platforms=validate_disabled_platforms(
            body.disabled_platforms or [], body.platforms
        ),
        icon_data=validate_icon(body.icon_data),
        created_at=now,
        updated_at=now,
        enabled=True,
    )
    db.add(app)
    try:
        db.flush()
        replace_package_ids(db, app.id, identifiers)
        db.add(AppCreation(key=key, body_hash=digest, app_id=app.id))
        audit(db, request, context, "app.create", app)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "APP_SLUG_EXISTS", "App 路径已被使用") from exc
    etag(response, app)
    return app_dto(db, app)


@router.get("/{id}", response_model=App, operation_id="get_apps")
def read_app(id: UUID, response: Response, db: DB):
    app = get_app(db, id)
    etag(response, app)
    return app_dto(db, app)


@router.patch(
    "/{id}", response_model=App, operation_id="update_apps", dependencies=[Depends(require_csrf)]
)
def update_app(
    id: UUID,
    body: AppUpdate,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    fields = body.model_dump(exclude_unset=True)
    if not fields or any(v is None and k != "description" for k, v in fields.items()):
        raise AppError(422, "VALIDATION_ERROR", "更新字段不能为空")
    if "name" in fields and not fields["name"].strip():
        raise AppError(422, "VALIDATION_ERROR", "App 名称不能为空")
    if "platforms" in fields and len(set(fields["platforms"])) != len(fields["platforms"]):
        raise AppError(422, "VALIDATION_ERROR", "平台不可重复")
    app = get_app(db, id, lock=True)
    require_revision(if_match, app.revision)
    if app.archived_at:
        raise AppError(409, "APP_ARCHIVED", "应用已归档，请先恢复后再编辑；恢复不会自动启用分发")
    platforms = fields.get("platforms", app.platforms)
    if "icon_data" in fields:
        fields["icon_data"] = validate_icon(fields["icon_data"])
    if "disabled_platforms" in fields:
        fields["disabled_platforms"] = validate_disabled_platforms(
            fields["disabled_platforms"], platforms
        )
        check_platform_pause(db, app, fields["disabled_platforms"])
    elif "platforms" in fields:
        fields["disabled_platforms"] = [p for p in app.disabled_platforms if p in platforms]
    if fields.get("enabled") is False and app.enabled:
        check_platform_pause(db, app, app.platforms)
    check_platform_removal(db, app, platforms)
    if "allowed_package_ids" in fields:
        identifiers = normalize_package_ids(fields.pop("allowed_package_ids"), platforms)
        replace_package_ids(db, app.id, identifiers)
    elif "platforms" in fields:
        identifiers = [item for item in package_ids(db, app.id) if item["platform"] in platforms]
        replace_package_ids(db, app.id, normalize_package_ids(identifiers, platforms))
    for key, value in fields.items():
        setattr(app, key, value if value is not None else "")
    app.updated_at, app.revision = utcnow(), app.revision + 1
    audit(db, request, context, "app.update", app)
    db.commit()
    etag(response, app)
    return app_dto(db, app)


@router.get(
    "/{id}/archive-impact", response_model=AppArchiveImpact, operation_id="get_app_archive_impact"
)
def get_archive_impact(id: UUID, db: DB):
    return archive_impact(db, get_app(db, id))


def lifecycle(id, request, response, db, context, if_match, restore):
    app = get_app(db, id, lock=True)
    require_revision(if_match, app.revision)
    if restore:
        if not app.archived_at:
            raise AppError(409, "APP_NOT_ARCHIVED", "应用未归档")
        app.archived_at = None
    else:
        if app.archived_at:
            raise AppError(409, "APP_ARCHIVED", "应用已经归档")
        impact = archive_impact(db, app)
        if not impact["can_archive"]:
            raise AppError(409, "APP_ARCHIVE_BLOCKED", "；".join(impact["blockers"]))
        app.archived_at = utcnow()
    # Restore is intentionally disabled: historical distribution never reopens implicitly.
    app.enabled = False
    app.updated_at, app.revision = utcnow(), app.revision + 1
    audit(db, request, context, "app.restore" if restore else "app.archive", app)
    db.commit()
    etag(response, app)
    return app_dto(db, app)


@router.post(
    "/{id}/archive",
    response_model=App,
    operation_id="archive_app",
    dependencies=[Depends(require_csrf)],
)
def archive_app(
    id: UUID,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    return lifecycle(id, request, response, db, context, if_match, False)


@router.post(
    "/{id}/restore",
    response_model=App,
    operation_id="restore_app",
    dependencies=[Depends(require_csrf)],
)
def restore_app(
    id: UUID,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    return lifecycle(id, request, response, db, context, if_match, True)


@router.delete(
    "/{id}", status_code=204, operation_id="delete_app", dependencies=[Depends(require_csrf)]
)
def delete_app(
    id: UUID,
    request: Request,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    app = get_app(db, id, lock=True)
    require_revision(if_match, app.revision)
    # Check registered children; database foreign keys remain the final deletion guard.
    for table in Base.metadata.tables.values():
        if table.name == "allowed_package_ids":
            continue  # Owned configuration cascades; package/task references still block deletion.
        if "app_id" in table.c and any(
            fk.target_fullname == "applications.id" for fk in table.c.app_id.foreign_keys
        ):
            if db.scalar(select(func.count()).select_from(table).where(table.c.app_id == id)):
                raise AppError(409, "APP_IN_USE", "App 已有关联数据，请停用而非删除")
    audit(db, request, context, "app.delete", app)
    db.delete(app)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "APP_IN_USE", "App 已有关联数据，请停用而非删除") from exc
