"""Parse a verified COS package through the existing isolated parser."""

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import select

from app.api.contracts import PackageInfo
from app.api.library import validate_scope
from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.applications.service import platform_enabled
from app.domains.auth.service import utcnow
from app.domains.distribution.feishu import create_delivery
from app.domains.distribution.models import DebugRecord, PackageIngestionRecord, RuleRecord
from app.domains.distribution.service import RetryLater, digest, enqueue, must_get
from app.domains.library.models import (
    PackageRecord,
    PublicationPackage,
    PublicationRecord,
    VersionRecord,
)
from app.domains.storage.models import StoredObject
from app.domains.storage.package_ingestion import binding_for
from app.domains.storage.service import adapter, store_canonical

PARSER_METADATA = {
    "package_identifier",
    "version_name",
    "build_number",
    "min_os",
    "architectures",
    "signer_fingerprints",
    "signature_status",
    "parser_version",
}


def _safe_manifest(value):
    if not isinstance(value, dict) or value.get("schema_version", "1") != "1":
        raise AppError(422, "INVALID_PACKAGE_MANIFEST", "manifest 格式或版本不受支持")
    platform = value.get("platform")
    file_name = value.get("file_name")
    if platform not in {"android", "ios"} or not isinstance(file_name, str):
        raise AppError(422, "INVALID_PACKAGE_MANIFEST", "manifest 缺少平台或文件名")
    file_name = file_name.strip()
    if (
        not file_name
        or len(file_name) > 255
        or "/" in file_name
        or "\\" in file_name
        or file_name in {".", ".."}
        or not file_name.lower().endswith((".apk", ".ipa"))
    ):
        raise AppError(422, "INVALID_PACKAGE_MANIFEST", "manifest 文件名不合法")
    return {"schema_version": "1", "platform": platform, "file_name": file_name}


def _archive_manifest(path: Path, object_key: str) -> dict | None:
    """Recognize Joice's outer build archive without trusting its extension."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name and not name.endswith("/")]
            packages = [
                name
                for name in names
                if name.count("/") <= 1 and name.lower().endswith((".apk", ".ipa"))
            ]
            if len(packages) != 1 or "build-info.json" not in names:
                return None
            package_name = packages[0]
            platform = "android" if package_name.lower().endswith(".apk") else "ios"
            object_parts = object_key.strip("/").split("/")
            if (
                object_parts
                and object_parts[0] in {"android", "ios"}
                and object_parts[0] != platform
            ):
                raise AppError(422, "INVALID_PACKAGE_ARCHIVE", "归档平台目录与内部安装包类型不一致")
            declared = (
                archive.read(f"{package_name}.sha256").decode("utf-8", errors="strict").split()[0]
            )
            digest = hashlib.sha256(archive.read(package_name)).hexdigest()
            if declared.lower() != digest:
                raise AppError(422, "INVALID_PACKAGE_ARCHIVE", "归档内安装包摘要校验失败")
            info = json.loads(archive.read("build-info.json").decode("utf-8"))
            if not isinstance(info, dict):
                raise ValueError
            return {
                "schema_version": "archive-1",
                "platform": platform,
                "file_name": Path(package_name).name,
                "entry_name": package_name,
            }
    except AppError:
        raise
    except (OSError, ValueError, UnicodeError, zipfile.BadZipFile, KeyError, IndexError):
        return None


def _parser_paths(settings, task_id):
    job = str(task_id)
    inbox, outbox = settings.parser_inbox, settings.parser_outbox
    return inbox / f"{job}.json", inbox / f"{job}.bin", outbox / f"{job}.json"


def _prepare_parser_input(db, settings, task, ingestion, client, location):
    request_path, source_path, result_path = _parser_paths(settings, task.id)
    if request_path.is_file():
        return request_path, source_path, result_path
    settings.parser_inbox.mkdir(parents=True, exist_ok=True)
    settings.parser_outbox.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fuma-cos-parser-") as directory:
        package_path = Path(directory) / "package.bin"
        manifest_path = Path(directory) / "manifest.json"
        _, package_sha256 = client.download(
            ingestion.object_key, package_path, expected_size=ingestion.object_size
        )
        if package_sha256 != ingestion.object_sha256:
            raise AppError(409, "STORAGE_CONTENT_MISMATCH", "对象内容摘要与构建事件不一致")
        archive = _archive_manifest(package_path, ingestion.object_key)
        if ingestion.manifest_key == ingestion.object_key:
            if ingestion.manifest_sha256 != ingestion.object_sha256 or archive is None:
                raise AppError(422, "INVALID_PACKAGE_ARCHIVE", "归档对象缺少可验证的构建内容")
            manifest = archive
        else:
            client.download(ingestion.manifest_key, manifest_path, max_size=16 * 1024 * 1024)
            manifest = _safe_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            if archive and (
                manifest["platform"] != archive["platform"]
                or manifest["file_name"] != archive["file_name"]
            ):
                raise AppError(422, "INVALID_PACKAGE_ARCHIVE", "manifest 与归档内部安装包不一致")
        temporary = source_path.with_suffix(".tmp")
        if archive:
            with zipfile.ZipFile(package_path) as bundle:
                temporary.write_bytes(bundle.read(archive["entry_name"]))
            payload_sha256 = hashlib.sha256(temporary.read_bytes()).hexdigest()
            task.payload = {
                **task.payload,
                "package_sha256": payload_sha256,
                "archive_file_name": Path(ingestion.object_key).name,
            }
        else:
            shutil.copyfile(package_path, temporary)
        os.replace(temporary, source_path)
    request_temp = request_path.with_suffix(".tmp")
    request_temp.write_text(
        json.dumps(
            {
                "platform": manifest["platform"],
                "sha256": task.payload.get("package_sha256", ingestion.object_sha256),
            }
        ),
        encoding="utf-8",
    )
    os.replace(request_temp, request_path)
    task.payload = {
        **task.payload,
        "platform": manifest["platform"],
        "file_name": manifest["file_name"],
        "parser_started_at": utcnow().isoformat(),
    }
    ingestion.state = "parsing"
    ingestion.updated_at = utcnow()
    db.commit()
    return request_path, source_path, result_path


def _parser_result(result_path, expected_sha256):
    if result_path.stat().st_size > 32768:
        raise AppError(422, "INVALID_PARSER_RESULT", "解析输出超过限制")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AppError(422, "INVALID_PARSER_RESULT", "解析输出不是有效 JSON") from None
    metadata = result.get("metadata") if isinstance(result, dict) else None
    if (
        result.get("ok") is not True
        or result.get("sha256") != expected_sha256
        or not isinstance(metadata, dict)
        or set(metadata) != PARSER_METADATA
    ):
        raise AppError(422, "PACKAGE_PARSE_FAILED", "安装包解析结果无效")
    return metadata


def _persist_package(
    db,
    settings,
    ingestion,
    binding,
    location,
    metadata,
    platform,
    file_name,
    package_path,
    package_sha256,
    is_archive,
):
    app = must_get(db, AppRecord, ingestion.app_id)
    if not app.enabled or not platform_enabled(app, platform):
        raise AppError(409, "APP_NOT_READY", "App 已停用或未启用该平台")
    validate_scope(db, app, platform, ingestion.channel, metadata["package_identifier"])
    package_size = package_path.stat().st_size
    if is_archive:
        package_id = uuid5(ingestion.id, package_sha256)
        source_object_key = "/".join(
            part
            for part in (
                location.prefix.strip("/"),
                binding.object_prefix.strip("/"),
                "packages",
                str(package_id),
                f"{package_sha256}.bin",
            )
            if part
        )
    else:
        package_id = uuid5(ingestion.id, ingestion.object_sha256)
        source_object_key = ingestion.object_key
    source = {
        "source_kind": "cos_v2",
        "event_id": ingestion.event_id,
        "object_key": source_object_key,
        "manifest_key": ingestion.manifest_key,
        "build": ingestion.build,
    }
    if is_archive:
        source["archive_object_key"] = ingestion.object_key
    values = {
        "id": package_id,
        "app_id": ingestion.app_id,
        "platform": platform,
        "mode": ingestion.channel,
        "file_name": file_name,
        "size_bytes": package_size,
        "sha256": package_sha256,
        **metadata,
        "source_kind": "cos",
        "source_snapshot": source,
        "storage_location_id": location.id,
        "state": "ready",
        "internal_notes": "",
        "revision": 1,
        "created_at": utcnow(),
    }
    PackageInfo.model_validate(values)
    package = db.scalar(select(PackageRecord).where(PackageRecord.id == package_id))
    if package is None:
        package = PackageRecord(**values)
        db.add(package)
        db.flush()
    elif (
        package.sha256 != package_sha256
        or package.storage_location_id != location.id
        or package.state != "ready"
    ):
        raise AppError(409, "PACKAGE_IDENTITY_CONFLICT", "相同 COS 事件已关联不同安装包")
    if is_archive:
        # Keep the event archive as provenance while serving the verified APK/IPA
        # from a canonical COS object whose digest matches the package itself.
        store_canonical(
            db,
            settings,
            package,
            package_path,
            location_id=location.id,
            object_key=source_object_key,
        )
        stored = db.scalar(
            select(StoredObject).where(
                StoredObject.package_id == package.id,
                StoredObject.location_id == location.id,
                StoredObject.kind == "canonical",
                StoredObject.state == "ready",
            )
        )
        if stored is None or stored.object_key != source_object_key:
            raise AppError(409, "STORAGE_CONTENT_MISMATCH", "安装包原件未能保存到绑定存储")
    else:
        stored = db.scalar(
            select(StoredObject).where(
                StoredObject.location_id == location.id,
                StoredObject.object_key == ingestion.object_key,
            )
        )
        if stored is None:
            db.add(
                StoredObject(
                    location_id=location.id,
                    package_id=package.id,
                    object_key=ingestion.object_key,
                    kind="canonical",
                    state="ready",
                    size_bytes=ingestion.object_size,
                    sha256=ingestion.object_sha256,
                    created_at=utcnow(),
                )
            )
        elif stored.package_id not in {None, package.id} or stored.sha256 != ingestion.object_sha256:
            raise AppError(409, "STORAGE_CONTENT_MISMATCH", "对象已关联不同安装包")
        elif stored.package_id is None:
            stored.package_id = package.id
            stored.state = "ready"
    ingestion.package_id = package.id
    if ingestion.channel == "release":
        publication = db.scalar(
            select(PublicationRecord)
            .join(PublicationPackage)
            .where(
                PublicationRecord.app_id == ingestion.app_id,
                PublicationRecord.mode == "release",
                PublicationPackage.package_id == package.id,
            )
            .order_by(PublicationRecord.created_at.desc())
        )
        if publication is None:
            version = VersionRecord(
                app_id=ingestion.app_id,
                display_name=ingestion.build["version"][:100],
                mode="release",
                release_notes="",
                revision=1,
                created_at=utcnow(),
            )
            db.add(version)
            db.flush()
            publication = PublicationRecord(
                app_id=ingestion.app_id,
                version_id=version.id,
                platform=platform,
                mode="release",
                created_at=utcnow(),
            )
            db.add(publication)
            db.flush()
            db.add(PublicationPackage(publication_id=publication.id, package_id=package.id))
        ingestion.publication_id = publication.id
        return package, None

    source_identity = digest({"event_id": ingestion.event_id, "sha256": ingestion.object_sha256})
    entry = db.scalar(
        select(DebugRecord).where(
            DebugRecord.app_id == ingestion.app_id,
            DebugRecord.source_identity == source_identity,
        )
    )
    if entry is None:
        entry = DebugRecord(
            persistent_package_id=package.id,
            app_id=ingestion.app_id,
            source_identity=source_identity,
            cache_identity=None,
            connector_id=None,
            revision=1,
            enabled=True,
            platform=platform,
            file_name=file_name,
            size_bytes=package_size,
            version_name=metadata["version_name"],
            build_number=metadata["build_number"],
            source_tag=ingestion.build["version"],
            source=source,
            cache_state="missing",
            downloaded_bytes=0,
            sha256=package_sha256,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(entry)
    else:
        entry.persistent_package_id = package.id
        entry.file_name = file_name
        entry.size_bytes = package_size
        entry.sha256 = package_sha256
        entry.source = source
        entry.updated_at = utcnow()
    return package, entry


def _queue_ready_notifications(db, settings, ingestion, entry, metadata):
    rule = db.get(RuleRecord, ingestion.rule_id)
    if rule is None or not rule.data.get("enabled"):
        return
    chat_ids = list(dict.fromkeys(rule.data.get("chat_ids", [])))
    if not chat_ids:
        return
    app = must_get(db, AppRecord, ingestion.app_id)
    card = {
        "title": "Debug 安装包已就绪",
        "summary": "COS 安装包已校验并解析完成，可在 Fuma 下载。",
        "app_name": app.name,
        "mode": ingestion.channel,
        "version_label": f"Tag: {ingestion.build.get('version', '未提供版本')}",
        "build_number": metadata.get("build_number"),
        "file_names": [entry.file_name],
        "result": "success",
        "occurred_at": utcnow().isoformat(),
        "page_url": f"{settings.site_url}/apps/{app.id}",
    }
    deliveries = [
        create_delivery(
            db,
            chat_id,
            card,
            rule_id=rule.id,
            app_id=ingestion.app_id,
            kind="build_ready",
            enqueue_task=False,
        )
        for chat_id in chat_ids
    ]
    enqueue(
        db,
        "notification",
        app_id=ingestion.app_id,
        payload={"delivery_ids": [str(delivery.id) for delivery in deliveries]},
        dedupe_key=f"cos_notification:{ingestion.id}",
    )


def parse_and_persist(db, settings, task):
    ingestion = must_get(db, PackageIngestionRecord, UUID(task.resource_id))
    if ingestion.state in {"ready", "pending_publish"}:
        return
    if ingestion.state not in {"verified", "parsing"}:
        raise AppError(409, "INGESTION_NOT_VERIFIED", "对象尚未完成校验")
    binding, location = binding_for(db, ingestion)
    client = adapter(settings, location)
    request_path, source_path, result_path = _prepare_parser_input(
        db, settings, task, ingestion, client, location
    )
    if not result_path.is_file():
        raise RetryLater(5)
    metadata = _parser_result(
        result_path, task.payload.get("package_sha256", ingestion.object_sha256)
    )
    platform = task.payload.get("platform")
    file_name = task.payload.get("file_name")
    if platform not in {"android", "ios"} or not isinstance(file_name, str):
        raise AppError(422, "INVALID_PACKAGE_MANIFEST", "解析任务缺少 manifest 元数据")
    _package, entry = _persist_package(
        db,
        settings,
        ingestion,
        binding,
        location,
        metadata,
        platform,
        file_name,
        source_path,
        task.payload.get("package_sha256", ingestion.object_sha256),
        bool(task.payload.get("archive_file_name")),
    )
    if entry is None:
        ingestion.state = "pending_publish"
    else:
        _queue_ready_notifications(db, settings, ingestion, entry, metadata)
        ingestion.state = "ready"
    ingestion.error_code = ingestion.error_message = None
    ingestion.updated_at = utcnow()
    db.commit()
    for path in (request_path, source_path, result_path):
        path.unlink(missing_ok=True)
