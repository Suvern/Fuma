import hashlib
import json
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.domains.auth.service import utcnow
from app.domains.distribution.service import must_get
from app.domains.github.crypto import SecretBox
from app.domains.storage.adapter import Adapter
from app.domains.storage.models import StorageCredential, StorageLocation, StoredObject


def adapter(settings, location):
    values = _credential_values(settings, location)
    return Adapter(location, values)


def _credential_values(settings, location, *, candidate=False):
    box = SecretBox(settings)
    if isinstance(location, StorageCredential):
        profile = location
    elif location.credential_id:
        profile = getattr(location, "credential", None)
        if profile is None:
            raise AppError(503, "STORAGE_CREDENTIAL_UNAVAILABLE", "存储凭据档案不存在")
    else:
        profile = None
    if profile is not None:
        encrypted = (
            profile.candidate_credentials
            if candidate and profile.candidate_credentials
            else profile.encrypted_credentials
        )
        if not encrypted or not profile.enabled:
            raise AppError(503, "STORAGE_CREDENTIAL_UNAVAILABLE", "存储凭据档案不可用")
        scope = f"storage-credential:{profile.id}"
    else:
        encrypted = (
            location.candidate_credentials
            if candidate and location.candidate_credentials
            else location.encrypted_credentials
        )
        if not encrypted:
            raise AppError(503, "STORAGE_CREDENTIAL_UNAVAILABLE", "存储桶缺少凭据")
        scope = f"storage:{location.id}"
    return json.loads(box.decrypt(encrypted, scope))


def credential_values(settings, location, *, candidate=False):
    """Resolve shared or legacy credentials for workers and adapters."""
    return _credential_values(settings, location, candidate=candidate)


def ready_location(db, id, mode="private"):
    location = must_get(db, StorageLocation, id)
    if not location.enabled or location.status != "ready" or location.read_mode != mode:
        raise AppError(409, "STORAGE_NOT_READY", "请选择已启用且测试通过的对应模式存储")
    return location


def probe(db, settings, task):
    location = must_get(db, StorageLocation, UUID(task.resource_id))
    if location.task_id != task.id:
        raise AppError(409, "STORAGE_TEST_STALE", "配置已变化，请重新测试")
    if location.credential_id:
        from sqlalchemy import select

        profile = db.scalar(
            select(StorageCredential).where(StorageCredential.id == location.credential_id)
        )
        if profile is None:
            raise AppError(503, "STORAGE_CREDENTIAL_UNAVAILABLE", "存储凭据档案不存在")
        client = Adapter(location, _credential_values(settings, profile, candidate=True))
    elif location.candidate_credentials:
        client = Adapter(location, _credential_values(settings, location, candidate=True))
    else:
        client = adapter(settings, location)
    key = (
        "/".join(part for part in (location.prefix.strip("/"), "probes", str(task.id)) if part)
        + ".bin"
    )
    capabilities = {}
    failure = None
    cleanup_failure = None
    content = b"Fuma storage capability probe\n"
    sha = hashlib.sha256(content).hexdigest()
    record = db.scalar(
        select(StoredObject).where(
            StoredObject.location_id == location.id, StoredObject.object_key == key
        )
    )
    if record is None:
        record = StoredObject(
            location_id=location.id,
            object_key=key,
            kind="probe",
            state="pending",
            size_bytes=len(content),
            sha256=sha,
            created_at=utcnow(),
        )
        db.add(record)
        db.commit()
    try:
        client.check_bucket()
        with tempfile.TemporaryDirectory(prefix="fuma-storage-probe-") as temporary:
            path = Path(temporary) / "probe.bin"
            path.write_bytes(content)
            client.put(key, path, sha, public=location.read_mode == "public")
        capabilities["write"] = "passed"
        client.verify(key, len(content), sha, public=location.read_mode == "public", full=True)
        capabilities["read"] = "passed"
        capabilities["anonymous"] = "denied" if location.read_mode == "private" else "readable"
    except AppError as exc:
        failure = exc
    except Exception:
        failure = AppError(503, "STORAGE_PROBE_FAILED", "连接测试失败，请检查云配置")
    finally:
        try:
            client.delete(key)
            record.state = "deleted"
            capabilities["cleanup"] = "passed"
        except Exception:
            cleanup_failure = AppError(
                503,
                "STORAGE_PROBE_CLEANUP_FAILED",
                "测试对象清理未确认，残留位置见能力检查；重新测试可重试清理",
            )
            capabilities["cleanup"] = "failed: " + key
            record.state = "failed"
    # Retry also reconciles probe remnants from earlier tests, never arbitrary bucket keys.
    if not cleanup_failure:
        for old in db.scalars(
            select(StoredObject).where(
                StoredObject.location_id == location.id,
                StoredObject.kind == "probe",
                StoredObject.state != "deleted",
                StoredObject.id != record.id,
            )
        ):
            try:
                client.delete(old.object_key)
                old.state = "deleted"
            except Exception:
                cleanup_failure = AppError(
                    503, "STORAGE_PROBE_CLEANUP_FAILED", "历史测试对象清理未确认"
                )
                capabilities["cleanup"] = "failed: " + old.object_key
    error = cleanup_failure or failure
    if not error and location.credential_id:
        profile = db.scalar(
            select(StorageCredential).where(StorageCredential.id == location.credential_id)
        )
        if profile and profile.candidate_credentials:
            profile.encrypted_credentials = profile.candidate_credentials
            profile.candidate_credentials = None
            profile.revision += 1
            profile.updated_at = utcnow()
        if location.candidate_credentials:
            location.encrypted_credentials = location.candidate_credentials
            location.candidate_credentials = None
    elif not error and location.candidate_credentials:
        location.encrypted_credentials = location.candidate_credentials
        location.candidate_credentials = None
    location.status = "failed" if error else "ready"
    location.error_message = error.message if error else None
    location.capabilities, location.checked_at = capabilities, utcnow()
    location.revision += 1
    db.commit()
    if error:
        raise error


def store_canonical(db, settings, package, path, *, location_id=None, object_key=None):
    # A local package can acquire a cloud original without switching existing
    # downloads before upload and verification have both completed.
    target_id = location_id or package.storage_location_id
    if not target_id:
        return
    location = ready_location(db, target_id)
    key = object_key or "/".join(
        part
        for part in (
            location.prefix.strip("/"),
            "apps",
            str(package.app_id),
            "packages",
            str(package.id),
            f"{package.sha256}.bin",
        )
        if part
    )
    record = db.scalar(
        select(StoredObject).where(
            StoredObject.location_id == location.id, StoredObject.object_key == key
        )
    )
    if record is None:
        record = StoredObject(
            location_id=location.id,
            package_id=package.id,
            object_key=key,
            kind="canonical",
            state="pending",
            size_bytes=package.size_bytes,
            sha256=package.sha256,
            created_at=utcnow(),
        )
        db.add(record)
    # Record the authorized external step before outbound I/O, including retries
    # of an existing pending/ready object. Callers recheck actor and App scope
    # before promoting package readiness or switching legacy download pointers.
    db.commit()
    client = adapter(settings, location)
    if record.state != "ready":
        client.put(key, path, package.sha256)
    client.verify(key, package.size_bytes, package.sha256, full=True)
    record.state = "ready"
    db.commit()


def canonical(db, package):
    record = db.scalar(
        select(StoredObject).where(
            StoredObject.package_id == package.id,
            StoredObject.location_id == package.storage_location_id,
            StoredObject.kind == "canonical",
            StoredObject.state == "ready",
        )
    )
    if not record:
        raise AppError(503, "STORAGE_NOT_READY", "私有原件暂时不可用")
    return record


def cloud_grant(db, settings, package):
    record = canonical(db, package)
    location = must_get(db, StorageLocation, record.location_id)
    # Disabled positions still serve historical packages, but every grant rechecks actual access.
    client = adapter(settings, location)
    client.verify(record.object_key, package.size_bytes, package.sha256)
    return client.presign(record.object_key, file_name=package.file_name)
