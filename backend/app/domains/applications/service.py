"""App configuration shared by administration and future parsed package ingestion."""

import re

from sqlalchemy import delete, select

from app.core.errors import AppError
from app.domains.applications.models import AllowedPackageIdRecord
from app.domains.distribution.models import DebugRecord, TaskRecord

IDENTIFIER_PATTERNS = {
    "android": re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+"),
    "ios": re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"),
}


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
