"""Assemble uploads and exchange bounded results with the credential-free offline parser."""

import hashlib
import json
import os
import shutil
from datetime import timedelta
from uuid import UUID, uuid5

from sqlalchemy import select

from app.api.library import active_app, package_file, upload_dir, validate_scope
from app.core.errors import AppError
from app.domains.auth.service import utcnow
from app.domains.distribution.service import RetryLater
from app.domains.library.models import PackageRecord, UploadRecord


def ingest(db, settings, task):
    upload = db.get(UploadRecord, UUID(task.resource_id))
    if upload.state == "ready":
        return
    if upload.state != "processing" or upload.task_id != task.id:
        raise AppError(409, "UPLOAD_TASK_STALE", "上传处理任务已失效")
    if upload.source_snapshot and not task.payload.get("parser_sha256"):
        from app.domains.library.github_import import prepare

        prepare(db, settings, upload, task)
    job = str(task.id)
    inbox, outbox = settings.parser_inbox, settings.parser_outbox
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    request_path, source = inbox / (job + ".json"), inbox / (job + ".bin")
    result_path = outbox / (job + ".json")
    if not request_path.exists():
        digest = hashlib.sha256()
        size = 0
        temporary = source.with_suffix(".tmp")
        try:
            with temporary.open("wb") as target:
                for part in sorted(upload.parts, key=lambda p: p["part_number"]):
                    piece = hashlib.sha256()
                    count = 0
                    with (upload_dir(settings, upload.id) / str(part["part_number"])).open(
                        "rb"
                    ) as stream:
                        while chunk := stream.read(1024**2):
                            digest.update(chunk)
                            piece.update(chunk)
                            target.write(chunk)
                            count += len(chunk)
                            size += len(chunk)
                            if count > part["size_bytes"] or size > upload.declared_size:
                                raise AppError(409, "UPLOAD_CHANGED", "分片内容已改变")
                    if count != part["size_bytes"] or piece.hexdigest() != part["sha256"]:
                        raise AppError(409, "UPLOAD_CHANGED", "分片校验失败")
                if size != upload.declared_size:
                    raise AppError(409, "UPLOAD_CHANGED", "上传总长度不匹配")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, source)
            request_temp = request_path.with_suffix(".tmp")
            request_temp.write_text(
                json.dumps({"platform": upload.platform, "sha256": digest.hexdigest()})
            )
            os.replace(request_temp, request_path)
            task.payload = {
                **task.payload,
                "parser_sha256": digest.hexdigest(),
                "parser_started_at": utcnow().isoformat(),
            }
            task.phase = "parsing"
            db.commit()
        finally:
            temporary.unlink(missing_ok=True)
    if not result_path.is_file():
        from datetime import datetime

        started = datetime.fromisoformat(
            task.payload.get("parser_started_at", task.created_at.isoformat())
        )
        if utcnow() - started > timedelta(minutes=5):
            raise AppError(
                503, "PARSER_UNAVAILABLE", "隔离解析器 5 分钟内未返回；检查 parser 服务，随后重试"
            )
        raise RetryLater(5)
    if result_path.stat().st_size > 32768:
        raise AppError(422, "INVALID_PARSER_RESULT", "解析输出超过限制")
    result = json.loads(result_path.read_text())
    if not result.get("ok"):
        raise AppError(
            422, "PACKAGE_PARSE_FAILED", str(result.get("error_message", "解析失败"))[:300]
        )
    metadata = result.get("metadata", {})
    expected = {
        "package_identifier",
        "version_name",
        "build_number",
        "min_os",
        "architectures",
        "signer_fingerprints",
        "signature_status",
        "parser_version",
    }
    if set(metadata) != expected or result.get("sha256") != task.payload.get("parser_sha256"):
        raise AppError(422, "INVALID_PARSER_RESULT", "解析结果身份不匹配")
    # Validate provider output before it is persisted, independently of the parser process.
    from pydantic import ValidationError

    from app.api.contracts import PackageInfo

    # A crash before database commit must reuse the same destination on retry.
    package_id = uuid5(upload.id, result["sha256"])
    values = dict(
        id=package_id,
        app_id=upload.app_id,
        platform=upload.platform,
        mode=upload.mode,
        file_name=upload.file_name,
        size_bytes=upload.declared_size,
        sha256=result["sha256"],
        **metadata,
        source_kind="github" if upload.source_snapshot else "upload",
        source_snapshot=upload.source_snapshot,
        storage_location_id=upload.storage_location_id,
        state="ready",
        internal_notes="",
        revision=1,
        created_at=utcnow(),
    )
    try:
        PackageInfo.model_validate(values)
    except ValidationError as exc:
        raise AppError(422, "INVALID_PARSER_RESULT", "解析结果字段不合法") from exc
    app = active_app(db, upload.app_id)
    validate_scope(db, app, upload.platform, upload.mode, metadata["package_identifier"])
    package = db.scalar(
        select(PackageRecord).where(
            PackageRecord.app_id == upload.app_id,
            PackageRecord.platform == upload.platform,
            PackageRecord.mode == upload.mode,
            PackageRecord.sha256 == result["sha256"],
        )
    )
    conflict = db.scalar(
        select(PackageRecord).where(
            PackageRecord.app_id == upload.app_id,
            PackageRecord.platform == upload.platform,
            PackageRecord.mode == upload.mode,
            PackageRecord.package_identifier == metadata["package_identifier"],
            PackageRecord.build_number == metadata["build_number"],
            PackageRecord.sha256 != result["sha256"],
            PackageRecord.state != "deleted",
        )
    )
    if conflict:
        raise AppError(
            409, "PACKAGE_IDENTITY_CONFLICT", "同包标识和构建号已存在不同内容，请使用新的构建号"
        )
    if package is None or package.state == "deleted":
        target = package_file(settings, package.id if package else package_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Never move the parser input while the offline process might still be reading it.
        staged = target.with_suffix(".tmp")
        try:
            shutil.copyfile(source, staged)
            with staged.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != result["sha256"]:
                    raise AppError(409, "PACKAGE_HASH_MISMATCH", "入库文件校验失败")
                os.fsync(stream.fileno())
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
        if package is None:
            package = PackageRecord(**values)
            db.add(package)
        else:
            # Physical deletion retains identity and audit history. A verified
            # re-upload restores that identity with a fresh retention window.
            package.storage_location_id = upload.storage_location_id
            package.created_at = utcnow()
            package.revision += 1
        package.state = "processing"
        db.flush()
    elif (
        package.state not in {"processing", "ready"}
        or not package_file(settings, package.id).is_file()
    ):
        raise AppError(409, "PACKAGE_NOT_READY", "相同内容存在未完成清理或丢失文件，请先处理原记录")
    from app.domains.storage.service import store_canonical

    target_location_id = upload.storage_location_id or package.storage_location_id
    if (
        upload.storage_location_id
        and package.storage_location_id
        and package.storage_location_id != upload.storage_location_id
    ):
        raise AppError(
            409,
            "PACKAGE_STORAGE_CONFLICT",
            "相同内容已存入另一私有存储；请选择原存储位置，原安装包和下载入口保持可用",
        )
    store_canonical(
        db,
        settings,
        package,
        package_file(settings, package.id),
        location_id=target_location_id,
    )
    # Cloud round-trips may commit checkpoints; recheck the app before publishing readiness.
    app = active_app(db, upload.app_id)
    validate_scope(db, app, upload.platform, upload.mode, metadata["package_identifier"])
    if upload.source_snapshot and app.repository != upload.source_snapshot["repository"]:
        raise AppError(409, "SOURCE_CHANGED", "导入期间仓库关联已变化")
    db.refresh(package, with_for_update=True)
    if package.storage_location_id not in {None, target_location_id}:
        raise AppError(409, "PACKAGE_STORAGE_CONFLICT", "入库期间原件位置已改变，请刷新后重试")
    if package.storage_location_id != target_location_id:
        package.storage_location_id = target_location_id
        package.revision += 1
    package.state = "ready"
    from app.domains.library.github_import import link_result

    link_result(db, upload, package)
    upload.package_id, upload.state, upload.error_message = package.id, "ready", None
    db.commit()
    # Readiness (and any legacy switch) is already committed. Staging cleanup
    # must not turn a successful import into a failed, potentially non-retryable
    # upload. The registered staging sweep retries leftovers for ready uploads.
    for path in (request_path, source, result_path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    shutil.rmtree(upload_dir(settings, upload.id), ignore_errors=True)
