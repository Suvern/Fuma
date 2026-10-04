"""Only remove staging files registered to an upload; keep ready package contents."""

import shutil

from sqlalchemy import select

from app.domains.auth.service import utcnow
from app.domains.distribution.models import TaskRecord
from app.domains.library.models import UploadRecord


def cleanup_staging(db, settings, row):
    from app.api.library import upload_dir

    directory = upload_dir(settings, row.id)
    if directory.exists():
        shutil.rmtree(directory)
    cleanup_parser_jobs(db, settings, row)


def cleanup_parser_jobs(db, settings, row):
    for id in db.scalars(
        select(TaskRecord.id).where(
            TaskRecord.kind == "package_ingest", TaskRecord.resource_id == str(row.id)
        )
    ):
        # Withdraw requests first; a late parser result is picked up on the next sweep.
        for base, suffix in [
            (settings.parser_inbox, ".json"),
            (settings.parser_inbox, ".bin"),
            (settings.parser_inbox, ".tmp"),
            (settings.parser_outbox, ".json"),
            (settings.parser_outbox, ".tmp"),
        ]:
            (base / (str(id) + suffix)).unlink(missing_ok=True)


def cleanup_expired(db, settings):
    rows = list(
        db.scalars(
            select(UploadRecord).where(
                UploadRecord.state.in_(["receiving", "failed", "ready", "cancelled", "expired"])
            )
        )
    )
    for row in rows:
        if row.state in {"receiving", "failed"} and row.expires_at > utcnow():
            continue
        # Use the same upload row lock as completion; no lock is held while scheduling work.
        db.refresh(row, with_for_update=True)
        if row.state == "processing":
            db.rollback()
            continue
        try:
            cleanup_staging(db, settings, row)
        except OSError:
            # Keep reservation/state until a later sweep can confirm cleanup.
            db.rollback()
            continue
        if row.state in {"receiving", "failed"}:
            row.state = "expired"
            row.error_message = "上传会话已超过 24 小时，暂存分片已清理；请重新上传"
        row.parts = []
        db.commit()


def delete_package(db, settings, task):
    from uuid import UUID

    from app.api.library import active_app, package_file
    from app.api.library_management import deletion_impact
    from app.core.errors import AppError
    from app.domains.distribution.service import must_get
    from app.domains.library.models import PackageRecord
    from app.domains.storage.models import StorageLocation, StoredObject
    from app.domains.storage.service import adapter

    package = must_get(db, PackageRecord, UUID(task.resource_id))
    if package.state == "deleted":
        return
    active_app(db, package.app_id)
    db.refresh(package, with_for_update=True)
    if deletion_impact(db, package)["blockers"]:
        raise AppError(409, "PACKAGE_IN_USE", "删除执行前引用检查未通过")
    for obj in db.scalars(
        select(StoredObject).where(
            StoredObject.package_id == package.id, StoredObject.state != "deleted"
        )
    ):
        adapter(settings, must_get(db, StorageLocation, obj.location_id)).delete(obj.object_key)
        obj.state = "deleted"
    package_file(settings, package.id).unlink(missing_ok=True)
    package.state, package.revision = "deleted", package.revision + 1
    db.commit()
