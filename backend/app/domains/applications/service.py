"""App configuration shared by administration and future parsed package ingestion."""

import base64
import binascii
import re

from sqlalchemy import delete, func, or_, select

from app.core.errors import AppError
from app.domains.applications.models import AllowedPackageIdRecord
from app.domains.distribution.models import DebugRecord, RuleRecord, TaskRecord
from app.domains.github.models import GithubReleasePolicy
from app.domains.library.models import PackageRecord, PublicationRecord, UploadRecord

IDENTIFIER_PATTERNS = {
    "android": re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+"),
    "ios": re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"),
}


def platform_enabled(app, platform):
    return bool(
        app
        and app.enabled
        and not app.archived_at
        and platform in app.platforms
        and platform not in (app.disabled_platforms or [])
    )


def require_platform_enabled(app, platform):
    if not platform_enabled(app, platform):
        raise AppError(409, "PLATFORM_DISABLED", "应用或该平台已停用，请先检查平台配置")


def validate_icon(value):
    if not value:
        return ""
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", value)
    if not match:
        raise AppError(422, "INVALID_APP_ICON", "图标须为 PNG、JPEG 或 WebP 图片")
    try:
        raw = base64.b64decode(match[2], validate=True)
    except (binascii.Error, ValueError):
        raise AppError(422, "INVALID_APP_ICON", "图标编码无效") from None
    valid_magic = {
        "png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpeg": raw.startswith(b"\xff\xd8\xff"),
        "webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
    }
    if len(raw) > 65536 or not valid_magic[match[1]]:
        raise AppError(422, "INVALID_APP_ICON", "图标格式与内容不符或超过 64 KiB")
    return value


def validate_disabled_platforms(values, platforms):
    if len(values) != len(set(values)) or not set(values) <= set(platforms):
        raise AppError(422, "INVALID_PLATFORM_STATE", "停用平台必须属于已选择的平台且不能重复")
    return values


def check_platform_pause(db, app, values):
    paused = set(values) - set(app.disabled_platforms or [])
    if paused and db.scalar(
        select(PublicationRecord.id)
        .where(
            PublicationRecord.app_id == app.id,
            PublicationRecord.platform.in_(paused),
            PublicationRecord.access_state.in_(
                ["public", "publishing", "reclaiming", "reclaim_failed"]
            ),
        )
        .limit(1)
    ):
        raise AppError(
            409,
            "PUBLIC_ACCESS_PENDING",
            "该平台仍有公开副本或未完成访问收回，请先下架并完成收回后停用",
        )


def archive_impact(db, app):
    entries = db.scalar(
        select(func.count()).select_from(DebugRecord).where(DebugRecord.app_id == app.id)
    )
    active = db.scalar(
        select(func.count())
        .select_from(DebugRecord)
        .where(DebugRecord.app_id == app.id, DebugRecord.enabled.is_(True))
    )
    tasks = db.scalar(
        select(func.count())
        .select_from(TaskRecord)
        .where(TaskRecord.app_id == app.id, TaskRecord.state.in_(["queued", "running"]))
    )
    rules = sum(
        bool(row.data.get("enabled"))
        for row in db.scalars(select(RuleRecord).where(RuleRecord.app_id == app.id))
    )
    policy = db.get(GithubReleasePolicy, app.id)
    automatic = bool(policy and policy.auto_enabled)
    blockers = []
    if active:
        blockers.append(f"仍有 {active} 个启用的 Debug 包，请先停用")
    if tasks:
        blockers.append(f"仍有 {tasks} 个未完成任务，请等待或处理")
    if rules:
        blockers.append(f"仍有 {rules} 条启用的 Actions 规则，请先停用")
    if automatic:
        blockers.append("Release 自动导入仍开启，请先关闭")
    publications = db.scalar(
        select(func.count())
        .select_from(PublicationRecord)
        .where(
            PublicationRecord.app_id == app.id,
            or_(
                PublicationRecord.state == "published",
                PublicationRecord.access_state.in_(["publishing", "reclaiming", "reclaim_failed"]),
            ),
        )
    )
    uploads = db.scalar(
        select(func.count())
        .select_from(UploadRecord)
        .where(
            UploadRecord.app_id == app.id,
            UploadRecord.state.in_(["receiving", "processing", "failed"]),
        )
    )
    if publications:
        blockers.append(f"仍有 {publications} 个正式发布或未完成访问收回，请先下架并完成收回")
    if uploads:
        blockers.append(f"仍有 {uploads} 个上传会话，请完成或取消")
    return dict(
        app_id=app.id,
        revision=app.revision,
        can_archive=not blockers and app.archived_at is None,
        debug_entries=entries,
        active_debug_entries=active,
        active_tasks=tasks,
        active_actions_rules=rules,
        automatic_import_enabled=automatic,
        blockers=blockers,
    )


def normalize_package_ids(items, platforms):
    """Deduplicate within platform/mode, keeping the first spelling for display."""
    result = {}
    for item in items:
        platform, mode, identifier = item["platform"], item["mode"], item["identifier"]
        if platform not in platforms:
            raise AppError(422, "PACKAGE_PLATFORM_DISABLED", "包标识只能配置在已选择的平台下")
        if not IDENTIFIER_PATTERNS[platform].fullmatch(identifier):
            label = "Android 包名" if platform == "android" else "iOS Bundle ID"
            raise AppError(422, "INVALID_PACKAGE_IDENTIFIER", f"{label} 格式不合法，不支持通配符")
        normalized = identifier.lower() if platform == "ios" else identifier
        result.setdefault(
            (platform, mode, normalized), {**item, "normalized_identifier": normalized}
        )
    return list(result.values())


def package_ids(db, app_id):
    return [
        {"platform": row.platform, "mode": row.mode, "identifier": row.identifier}
        for row in db.scalars(
            select(AllowedPackageIdRecord)
            .where(AllowedPackageIdRecord.app_id == app_id)
            .order_by(
                AllowedPackageIdRecord.platform,
                AllowedPackageIdRecord.mode,
                AllowedPackageIdRecord.normalized_identifier,
            )
        )
    ]


def replace_package_ids(db, app_id, items):
    # Caller holds the App row lock; configuration and revision commit atomically.
    db.execute(delete(AllowedPackageIdRecord).where(AllowedPackageIdRecord.app_id == app_id))
    db.add_all(AllowedPackageIdRecord(app_id=app_id, **item) for item in items)


def check_platform_removal(db, app, platforms):
    removed = set(app.platforms) - set(platforms)
    if not removed:
        return
    if db.scalar(
        select(PackageRecord.id)
        .where(PackageRecord.app_id == app.id, PackageRecord.platform.in_(removed))
        .limit(1)
    ):
        raise AppError(409, "PLATFORM_IN_USE", "该平台仍有关联安装包及历史数据，不能移除")
    if db.scalar(
        select(UploadRecord.id)
        .where(
            UploadRecord.app_id == app.id,
            UploadRecord.platform.in_(removed),
            UploadRecord.state.in_(["receiving", "processing", "failed"]),
        )
        .limit(1)
    ):
        raise AppError(409, "PLATFORM_IN_USE", "该平台仍有未完成的上传，请完成或取消")
    entry = db.scalar(
        select(DebugRecord)
        .where(DebugRecord.app_id == app.id, DebugRecord.platform.in_(removed))
        .order_by(DebugRecord.id)
        .limit(1)
    )
    if entry:
        raise AppError(
            409,
            "PLATFORM_IN_USE",
            f"无法移除 {entry.platform}：仍有关联 Debug 包「{entry.file_name}」，"
            "停用的包也保留引用",
        )
    task = db.scalar(
        select(TaskRecord.id)
        .where(TaskRecord.app_id == app.id, TaskRecord.state.in_(["queued", "running"]))
        .limit(1)
    )
    if task:
        raise AppError(409, "PLATFORM_IN_USE", "应用仍有未完成任务，请完成任务后再移除平台")
