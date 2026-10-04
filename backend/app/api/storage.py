import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import func, select

from app.api import contracts as dto
from app.api.dependencies import CSRF, DB, Admin, require_revision
from app.api.library import audit
from app.core.errors import AppError
from app.domains.distribution.service import enqueue, lock, must_get, page
from app.domains.github.crypto import SecretBox
from app.domains.storage.adapter import validate_identity
from app.domains.storage.models import StorageLocation, StoredObject
from app.domains.storage.service import ready_location

router = APIRouter(tags=["Storage"])


def summary(db, row):
    count, size = db.execute(
        select(func.count(), func.coalesce(func.sum(StoredObject.size_bytes), 0)).where(
            StoredObject.location_id == row.id, StoredObject.state != "deleted"
        )
    ).one()
    return {
        **{
            key: getattr(row, key)
            for key in dto.StorageInfo.model_fields
            if key not in {"object_count", "managed_bytes"}
        },
        "object_count": count,
        "managed_bytes": size,
    }


@router.get(
    "/settings/storage-locations",
    response_model=dto.StoragePage,
    operation_id="list_storage_locations",
)
def locations(
    db: DB,
    admin: Admin,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
):
    rows = db.scalars(select(StorageLocation).order_by(StorageLocation.name, StorageLocation.id))
    return page(
        [
            summary(db, row)
            for row in rows
            if not q or q.casefold() in (row.name + row.bucket).casefold()
        ],
        page_number,
        page_size,
    )


@router.post(
    "/settings/storage-locations",
    response_model=dto.StorageInfo,
    operation_id="create_storage_location",
)
def create(body: dto.StorageCreate, request: Request, db: DB, admin: Admin, csrf: CSRF):
    validate_identity(body.provider, body.region, body.bucket, body.prefix)
    row = StorageLocation(
        id=uuid4(), **body.model_dump(exclude={"access_key_id", "access_key_secret"})
    )
    row.encrypted_credentials = SecretBox(request.app.state.settings).encrypt(
        json.dumps(
            {"access_key_id": body.access_key_id, "access_key_secret": body.access_key_secret}
        ),
        f"storage:{row.id}",
    )
    db.add(row)
    audit(db, request, admin, "storage.create", row.id)
    db.commit()
    return summary(db, row)


@router.get(
    "/settings/storage-locations/{id}",
    response_model=dto.StorageInfo,
    operation_id="get_storage_location",
)
def detail(id: UUID, db: DB, admin: Admin):
    return summary(db, must_get(db, StorageLocation, id))


def change(id, action, request, db, admin, revision):
    lock(db, "storage:configuration")
    row = must_get(db, StorageLocation, id)
    db.refresh(row, with_for_update=True)
    require_revision(revision, row.revision)
    if row.status == "testing":
        raise AppError(409, "STORAGE_TEST_RUNNING", "连接测试尚未结束，请查看任务")
    if action == "test":
        task = enqueue(db, "storage_probe", resource_id=str(id))
        row.task_id, row.status, row.error_message = task.id, "testing", None
    elif action == "make-default":
        ready_location(db, id)
        for old in db.scalars(select(StorageLocation).where(StorageLocation.is_default.is_(True))):
            old.is_default = False
            old.revision += 1
        row.is_default = True
    else:
        row.enabled = action == "enable"
        if not row.enabled:
            row.is_default = False
    row.revision += 1
    audit(db, request, admin, "storage." + action, id)
    db.commit()
    return summary(db, row)


@router.post(
    "/settings/storage-locations/{id}/test",
    response_model=dto.StorageInfo,
    operation_id="test_storage_location",
)
def test(
    id: UUID,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    return change(id, "test", request, db, admin, if_match)


@router.post(
    "/settings/storage-locations/{id}/make-default",
    response_model=dto.StorageInfo,
    operation_id="make_default_storage_location",
)
def make_default(
    id: UUID,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    return change(id, "make-default", request, db, admin, if_match)


@router.post(
    "/settings/storage-locations/{id}/disable",
    response_model=dto.StorageInfo,
    operation_id="disable_storage_location",
)
def disable(
    id: UUID,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    return change(id, "disable", request, db, admin, if_match)


@router.post(
    "/settings/storage-locations/{id}/enable",
    response_model=dto.StorageInfo,
    operation_id="enable_storage_location",
)
def enable(
    id: UUID,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    return change(id, "enable", request, db, admin, if_match)


@router.put(
    "/settings/storage-locations/{id}/credentials",
    response_model=dto.StorageInfo,
    operation_id="rotate_storage_credentials",
)
def credentials(
    id: UUID,
    body: dto.StorageCredentials,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    lock(db, "storage:configuration")
    row = must_get(db, StorageLocation, id)
    db.refresh(row, with_for_update=True)
    require_revision(if_match, row.revision)
    if row.status == "testing":
        raise AppError(409, "STORAGE_TEST_RUNNING", "请等待测试结束")
    row.candidate_credentials = SecretBox(request.app.state.settings).encrypt(
        json.dumps(body.model_dump()), f"storage:{id}"
    )
    task = enqueue(db, "storage_probe", resource_id=str(id))
    row.task_id, row.status, row.error_message = task.id, "testing", None
    row.revision += 1
    audit(db, request, admin, "storage.rotate_requested", id)
    db.commit()
    return summary(db, row)
