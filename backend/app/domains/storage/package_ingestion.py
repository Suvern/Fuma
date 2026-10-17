"""Trust-boundary checks for COS package event objects.

This first stage deliberately stops after a provider HEAD check.  Downloading,
parsing and publishing are separate stages so each transition can be retried and
verified without making an untrusted callback a package release.
"""

import tempfile
from pathlib import Path
from uuid import UUID

from app.core.errors import AppError
from app.domains.applications.models import AppStorageBindingRecord
from app.domains.auth.service import utcnow
from app.domains.distribution.models import PackageIngestionRecord
from app.domains.distribution.service import enqueue, must_get
from app.domains.storage.models import StorageLocation
from app.domains.storage.service import adapter


def effective_prefix(location: StorageLocation, app_prefix: str) -> str:
    return "/".join(part.strip("/") for part in (location.prefix, app_prefix) if part.strip("/"))


def assert_object_key(location: StorageLocation, app_prefix: str, object_key: str) -> None:
    prefix = effective_prefix(location, app_prefix)
    parts = object_key.split("/")
    if (
        not prefix
        or not object_key.startswith(prefix + "/")
        or any(part in {"", ".", ".."} for part in parts)
        or object_key.endswith("/")
    ):
        raise AppError(422, "STORAGE_KEY_INVALID", "对象不在该 App 的专用路径内")


def binding_for(db, ingestion: PackageIngestionRecord):
    binding = db.get(
        AppStorageBindingRecord,
        {"app_id": ingestion.app_id, "channel": ingestion.channel},
    )
    if binding is None:
        raise AppError(409, "APP_STORAGE_NOT_BOUND", "该通道尚未绑定存储位置")
    location = db.get(StorageLocation, binding.storage_location_id)
    if location is None or not location.enabled or location.status != "ready":
        raise AppError(409, "STORAGE_NOT_READY", "绑定的存储位置不可用，请重新配置")
    assert_object_key(location, binding.object_prefix, ingestion.object_key)
    assert_object_key(location, binding.object_prefix, ingestion.manifest_key)
    return binding, location


def verify_object(db, settings, task) -> None:
    ingestion = must_get(db, PackageIngestionRecord, UUID(task.resource_id))
    if ingestion.state in {"verified", "ready"}:
        return
    ingestion.state = "validating"
    ingestion.error_code = ingestion.error_message = None
    _binding, location = binding_for(db, ingestion)
    client = adapter(settings, location)
    actual_size, provider_sha256 = client.head(ingestion.object_key)
    if actual_size != ingestion.object_size:
        raise AppError(409, "STORAGE_CONTENT_MISMATCH", "对象大小与构建事件不一致")
    if provider_sha256 and provider_sha256.lower() != ingestion.object_sha256:
        raise AppError(409, "STORAGE_CONTENT_MISMATCH", "对象摘要与构建事件不一致")
    with tempfile.TemporaryDirectory(prefix="fuma-cos-ingest-") as directory:
        package_path = Path(directory) / "package.bin"
        manifest_path = Path(directory) / "manifest.json"
        _, package_sha256 = client.download(
            ingestion.object_key, package_path, expected_size=ingestion.object_size
        )
        if package_sha256 != ingestion.object_sha256:
            raise AppError(409, "STORAGE_CONTENT_MISMATCH", "对象内容摘要与构建事件不一致")
        _, manifest_sha256 = client.download(
            ingestion.manifest_key, manifest_path, max_size=16 * 1024 * 1024
        )
        if manifest_sha256 != ingestion.manifest_sha256:
            raise AppError(409, "STORAGE_CONTENT_MISMATCH", "manifest 摘要与构建事件不一致")
    ingestion.state = "verified"
    ingestion.verified_at = utcnow()
    ingestion.updated_at = utcnow()
    parse_task = enqueue(
        db,
        "cos_package_parse",
        resource_id=str(ingestion.id),
        app_id=ingestion.app_id,
        dedupe_key=f"cos_package_parse:{ingestion.id}",
    )
    ingestion.task_id = parse_task.id
    db.flush()


def package_ingestion_dto(row: PackageIngestionRecord) -> dict:
    return {
        "id": row.id,
        "app_id": row.app_id,
        "event_id": row.event_id,
        "channel": row.channel,
        "object_key": row.object_key,
        "object_size": row.object_size,
        "object_sha256": row.object_sha256,
        "manifest_key": row.manifest_key,
        "manifest_sha256": row.manifest_sha256,
        "build": row.build,
        "state": row.state,
        "package_id": row.package_id,
        "publication_id": row.publication_id,
        "task_id": row.task_id,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "verified_at": row.verified_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "status_url": f"/api/v1/package-ingestions/{row.id}",
    }
