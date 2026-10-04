"""Public files have publication-specific keys and an auditable reclaim workflow."""

from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.errors import AppError
from app.domains.auth.service import utcnow
from app.domains.distribution.service import must_get
from app.domains.library.models import PackageRecord, PublicationPackage, PublicationRecord
from app.domains.storage.models import StorageLocation, StoredObject
from app.domains.storage.service import adapter, ready_location


def objects(db, publication_id):
    return list(
        db.scalars(
            select(StoredObject)
            .where(StoredObject.publication_id == publication_id, StoredObject.state != "deleted")
            .order_by(StoredObject.id)
        )
    )


def reclaim(db, settings, row):
    failure = False
    for item in objects(db, row.id):
        client = adapter(settings, must_get(db, StorageLocation, item.location_id))
        try:
            client.delete(item.object_key)
            item.state = "deleted"
        except Exception:
            item.state = "failed"
            failure = True
        db.commit()
    if failure:
        raise AppError(
            503, "PUBLIC_RECLAIM_FAILED", "公开对象删除或源站验证失败；已停止新授权，请重试收回"
        )


def synchronize(db, settings, task):
    from app.api.library import active_app, package_file, validate_scope
    from app.domains.access.task_authorization import check_task_authorization

    row = must_get(db, PublicationRecord, UUID(task.resource_id))
    if row.access_task_id != task.id:
        raise AppError(409, "PUBLICATION_TASK_STALE", "发布访问任务已失效")
    action = task.payload["action"]
    if action == "reclaim":
        try:
            reclaim(db, settings, row)
        except AppError as exc:
            row.access_state, row.access_error = "reclaim_failed", exc.message
            row.revision += 1
            db.commit()
            raise
        row.state, row.access_state, row.access_error = "unpublished", "reclaimed", None
        row.revision += 1
        db.commit()
        return
    if row.access_state != "publishing":
        raise AppError(409, "PUBLICATION_TASK_STALE", "发布访问状态已改变")
    try:
        check_task_authorization(db, task)
        location = ready_location(db, row.public_storage_id, "public")
        client = adapter(settings, location)
        db.commit()
        client.check_bucket()
        packages = list(
            db.scalars(
                select(PackageRecord)
                .join(PublicationPackage)
                .where(PublicationPackage.publication_id == row.id)
            )
        )
        if not objects(db, row.id):
            for package in packages:
                db.add(
                    StoredObject(
                        location_id=location.id,
                        publication_id=row.id,
                        package_id=package.id,
                        object_key=f"{location.prefix}/publications/{row.id}/{uuid4()}/{package.id}.bin",
                        kind="public",
                        state="pending",
                        size_bytes=package.size_bytes,
                        sha256=package.sha256,
                        created_at=utcnow(),
                    )
                )
            db.commit()
        for item in objects(db, row.id):
            check_task_authorization(db, task)
            # This external step is now authorized to start. Release global
            # identity locks before transferring bytes; final publication has
            # its own locked recheck and compensates if authority changed.
            db.commit()
            package = must_get(db, PackageRecord, item.package_id)
            if item.state != "ready":
                client.put(
                    item.object_key, package_file(settings, package.id), package.sha256, public=True
                )
            client.verify(
                item.object_key, package.size_bytes, package.sha256, public=True, full=True
            )
            item.state = "ready"
            db.commit()
        check_task_authorization(db, task)
        app = active_app(db, row.app_id)
        db.refresh(row, with_for_update=True)
        if row.access_task_id != task.id or row.access_state != "publishing":
            raise AppError(409, "PUBLICATION_TASK_STALE", "发布访问状态已改变")
        for package in packages:
            validate_scope(db, app, row.platform, row.mode, package.package_identifier)
        row.state, row.access_state, row.published_at = "published", "public", utcnow()
        row.access_error = None
        row.revision += 1
        db.commit()
    except Exception as failure:
        db.rollback()
        row = must_get(db, PublicationRecord, row.id)
        row.state, row.access_state = "unpublished", "reclaiming"
        db.commit()
        try:
            reclaim(db, settings, row)
            row.access_state = "publish_failed"
            row.access_error = "公开副本发布失败，已清理生成的副本；请检查任务并重试发布"
        except Exception:
            row.access_state = "reclaim_failed"
            row.access_error = "公开副本发布失败，部分对象访问收回未确认；请重试收回"
        row.revision += 1
        db.commit()
        if isinstance(failure, AppError) and failure.code == "TASK_AUTHORIZATION_REVOKED":
            raise AppError(403, failure.code, f"任务发起者权限已撤销；{row.access_error}") from None
        raise AppError(503, "PUBLICATION_ACCESS_FAILED", row.access_error) from None
