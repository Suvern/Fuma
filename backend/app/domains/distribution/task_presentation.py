"""Management task context, built from authorized records and explicit safe result fields."""

from uuid import UUID

from app.domains.applications.models import AppRecord
from app.domains.distribution.models import DebugRecord, DeliveryRecord, EventRecord
from app.domains.distribution.service import task_dto
from app.domains.library.models import PackageRecord, PublicationRecord, UploadRecord, VersionRecord
from app.domains.storage.models import StorageLocation

SYSTEM_KINDS = {"cache_cleanup", "chat_sync", "storage_probe"}


def category(task):
    scheduled_sync = (
        task.kind == "release_sync"
        and task.created_actor_id is None
        and "policy_revision" in (task.payload or {})
    )
    return "system" if task.kind in SYSTEM_KINDS or scheduled_sync else "business"


def owned_resource(db, model, task):
    try:
        resource_id = UUID(task.resource_id or "")
    except ValueError:
        return None
    row = db.get(model, resource_id)
    # Corrupt/stale references must never reveal another application's object.
    return row if row and row.app_id == task.app_id else None


def count(result, key):
    value = result.get(key)
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def result_summary(task):
    if task.state not in {"succeeded", "partial_success"}:
        return None
    result = (task.payload or {}).get("result")
    result = result if isinstance(result, dict) else {}
    counts = [count(result, key) for key in ("created_count", "existing_count", "failed_count")]
    if task.kind in {"release_sync", "release_import"} and all(v is not None for v in counts):
        return f"新增 {counts[0]} 个、已存在 {counts[1]} 个、失败 {counts[2]} 个附件。"
    if task.kind == "release_sync":
        releases, assets = count(result, "release_count"), count(result, "asset_count")
        if releases is not None and assets is not None:
            return f"同步完成：{releases} 个 Release、{assets} 个附件。"
        return "Release 列表已同步；此历史任务未记录数量，请打开来源页查看当前结果。"
    if task.kind == "publication_access":
        return (
            "公开副本访问已收回。"
            if (task.payload or {}).get("action") == "reclaim"
            else "公开副本已发布，可到版本详情查看分发状态。"
        )
    return {
        "release_import": "附件导入处理已完成，可到应用的旧版 Debug 分发查看结果。",
        "cache_download": "文件已完成缓存，可以重新申请下载。",
        "package_ingest": "安装包已解析并入库；发布仍需单独操作。",
        "package_delete": "安装包文件已清理，历史记录保留。",
        "notification": "通知投递已处理，请查看投递记录；发送成功不等于已阅读。",
        "build_event": "构建分发处理已完成，文件和通知结果见构建事件。",
        "cache_cleanup": "本次缓存清理已完成，有效下载授权和传输中的文件会保留。",
        "chat_sync": "机器人可见群列表已更新。",
        "storage_probe": "存储连接与读写能力检查已完成。",
    }.get(task.kind, "任务已完成。")


def present_task(db, task):
    app = db.get(AppRecord, task.app_id) if task.app_id else None
    name = url = None
    base = f"/admin/apps/{app.id}" if app else None
    if task.kind in {"release_sync", "release_import"} and base:
        name, url = "GitHub Releases", base + "/releases"
    elif task.kind == "cache_download":
        row = owned_resource(db, DebugRecord, task)
        if row:
            name, url = row.file_name, f"/admin/debug/{row.id}"
    elif task.kind == "package_ingest":
        row = owned_resource(db, UploadRecord, task)
        if row and base:
            name, url = row.file_name, base + "/packages"
    elif task.kind == "package_delete":
        row = owned_resource(db, PackageRecord, task)
        if row and base:
            name, url = row.file_name, base + "/packages"
    elif task.kind == "publication_access":
        row = owned_resource(db, PublicationRecord, task)
        version = db.get(VersionRecord, row.version_id) if row else None
        if version and version.app_id == task.app_id:
            name, url = version.display_name, f"/admin/versions/{version.id}"
    elif task.kind == "build_event":
        row = owned_resource(db, EventRecord, task)
        if row:
            run = str(row.data.get("run_id", ""))
            name = f"构建 Run {run}" if run.isdecimal() and len(run) <= 32 else "构建事件"
            url = f"/admin/events/{row.id}"
    elif task.kind == "notification":
        row = owned_resource(db, DeliveryRecord, task)
        if row:
            name, url = row.chat_name, f"/admin/notifications/{row.id}"
    elif task.kind == "storage_probe" and task.app_id is None:
        try:
            row = db.get(StorageLocation, UUID(task.resource_id or ""))
        except ValueError:
            row = None
        name, url = row.name if row else "对象存储", "/admin/settings/storage"
    elif task.kind == "cache_cleanup":
        name, url = "本地文件缓存", "/admin/settings/cache" if task.app_id is None else None
    elif task.kind == "chat_sync" and task.app_id is None:
        name, url = "机器人可见群", "/admin/settings/feishu"
    return {
        **task_dto(task),
        "category": category(task),
        "app_name": app.name if app else None,
        "resource_name": name,
        "resource_url": url,
        "result_summary": result_summary(task),
    }
