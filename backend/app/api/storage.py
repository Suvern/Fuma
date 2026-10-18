import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import func, select

from app.api import contracts as dto
from app.api.dependencies import CSRF, DB, Admin, require_revision
from app.api.library import audit
from app.core.errors import AppError
from app.domains.auth.service import utcnow
from app.domains.distribution.service import enqueue, lock, must_get, page
from app.domains.github.crypto import SecretBox
from app.domains.storage.adapter import normalize_prefix, validate_identity
from app.domains.storage.models import StorageCredential, StorageLocation, StoredObject
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
            if key not in {"object_count", "managed_bytes", "credential_id", "credential_name"}
        },
        "object_count": count,
        "managed_bytes": size,
        "credential_id": row.credential_id,
        "credential_name": row.credential.name if row.credential else None,
    }


def _access_key_hint(value: str) -> str:
    value = value.strip()
    return value if len(value) <= 8 else value[:4] + "••••" + value[-4:]


def credential_summary(db, row):
    count = db.scalar(
        select(func.count())
        .select_from(StorageLocation)
        .where(StorageLocation.credential_id == row.id)
    )
    return {
        "id": row.id,
        "name": row.name,
        "provider": row.provider,
        "access_key_hint": row.access_key_hint,
        "location_count": count,
        "enabled": row.enabled,
        "revision": row.revision,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
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
    prefix = normalize_prefix(body.prefix)
    validate_identity(body.provider, body.region, body.bucket, prefix)
    credential = None
    if body.credential_id:
        credential = db.get(StorageCredential, body.credential_id)
        if credential is None or not credential.enabled:
            raise AppError(422, "STORAGE_CREDENTIAL_INVALID", "请选择仍可用的凭据档案")
        if credential.provider != body.provider:
            raise AppError(422, "STORAGE_CREDENTIAL_INVALID", "凭据云厂商与存储桶不一致")
        if body.access_key_id or body.access_key_secret:
            raise AppError(422, "STORAGE_CREDENTIAL_INVALID", "选择已有凭据时不要重复填写密钥")
    elif not body.access_key_id or not body.access_key_secret:
        raise AppError(422, "STORAGE_CREDENTIAL_REQUIRED", "请选择已有凭据或填写一组新凭据")
    else:
        credential = StorageCredential(
            id=uuid4(),
            name=body.credential_name or f"{body.name} 凭据",
            provider=body.provider,
            encrypted_credentials="",
            candidate_credentials=None,
            access_key_hint=_access_key_hint(body.access_key_id),
            enabled=True,
            revision=1,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        credential.encrypted_credentials = SecretBox(request.app.state.settings).encrypt(
            json.dumps(
                {"access_key_id": body.access_key_id, "access_key_secret": body.access_key_secret}
            ),
            f"storage-credential:{credential.id}",
        )
        db.add(credential)
    row = StorageLocation(
        id=uuid4(),
        name=body.name,
        provider=body.provider,
        region=body.region,
        bucket=body.bucket,
        prefix=prefix,
        read_mode=body.read_mode,
        encrypted_credentials="",
        candidate_credentials=None,
        credential_id=credential.id,
    )
    if body.access_key_id and body.access_key_secret:
        # Keep a legacy encrypted copy for safe rollback and old workers; new
        # reads always prefer the shared credential profile.
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
    "/settings/storage-credentials",
    response_model=dto.StorageCredentialPage,
    operation_id="list_storage_credentials",
)
def credentials_list(
    db: DB,
    admin: Admin,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: int = Query(50, ge=1, le=100),
):
    rows = db.scalars(
        select(StorageCredential).order_by(StorageCredential.name, StorageCredential.id)
    )
    return page([credential_summary(db, row) for row in rows], page_number, page_size)


@router.post(
    "/settings/storage-credentials",
    response_model=dto.StorageCredentialInfo,
    operation_id="create_storage_credential",
)
def create_credential(
    body: dto.StorageCredentialCreate,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
):
    now = utcnow()
    row = StorageCredential(
        id=uuid4(),
        name=body.name,
        provider=body.provider,
        encrypted_credentials="",
        candidate_credentials=None,
        access_key_hint=_access_key_hint(body.access_key_id),
        enabled=True,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    row.encrypted_credentials = SecretBox(request.app.state.settings).encrypt(
        json.dumps(body.model_dump(exclude_none=True)), f"storage-credential:{row.id}"
    )
    db.add(row)
    audit(db, request, admin, "storage.credentials.create", row.id)
    db.commit()
    return credential_summary(db, row)


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
    encrypted = SecretBox(request.app.state.settings).encrypt(
        json.dumps(body.model_dump()),
        f"storage-credential:{row.credential_id}" if row.credential_id else f"storage:{id}",
    )
    if row.credential_id:
        profile = db.get(StorageCredential, row.credential_id)
        if profile is None or not profile.enabled:
            raise AppError(409, "STORAGE_CREDENTIAL_UNAVAILABLE", "共享凭据档案不可用")
        profile.candidate_credentials = encrypted
        row.candidate_credentials = SecretBox(request.app.state.settings).encrypt(
            json.dumps(body.model_dump()), f"storage:{row.id}"
        )
        profile.revision += 1
        profile.updated_at = utcnow()
    else:
        row.candidate_credentials = encrypted
    task = enqueue(db, "storage_probe", resource_id=str(id))
    row.task_id, row.status, row.error_message = task.id, "testing", None
    row.revision += 1
    audit(db, request, admin, "storage.rotate_requested", id)
    db.commit()
    return summary(db, row)
