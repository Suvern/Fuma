import errno
import os
import re
import shutil
import zipfile
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import object_session

from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.auth.service import utcnow
from app.domains.distribution.models import CacheRecord, DebugRecord, GrantRecord, TransferLease
from app.domains.distribution.service import RetryLater, digest, enqueue, lock, state
from app.domains.github.service import get_github_client

DEFAULT_CACHE = {
    "max_file_bytes": 2147483648,
    "budget_bytes": 10737418240,
    "idle_ttl_seconds": 604800,
    "grant_ttl_seconds": 300,
    "download_concurrency": 2,
}

CACHE_FIELDS = (
    "cache_state",
    "downloaded_bytes",
    "sha256",
    "cache_error_code",
    "cache_updated_at",
    "last_access_at",
)


def cache_lock_key(entry):
    return f"cache_source:{entry.source_identity}"


def _project_cache(db, cache, **changes):
    """CacheRecord is canonical; entry fields are persisted read projections for existing DTOs."""
    lock(db, f"cache_source:{cache.source_identity}")
    db.flush()
    db.refresh(cache)
    for key, value in changes.items():
        setattr(cache, key, value)
    values = {key: getattr(cache, key) for key in CACHE_FIELDS}
    values["cache_identity"] = cache.source_identity
    db.execute(
        update(DebugRecord)
        .where(DebugRecord.source_identity == cache.source_identity)
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )


def source_cache(db, entry):
    lock(db, cache_lock_key(entry))
    cache = db.get(CacheRecord, entry.source_identity, populate_existing=True)
    if cache is None:
        # Compatibility for fixtures/imports created before the shared-cache migration.
        peers = db.scalars(
            select(DebugRecord)
            .where(DebugRecord.source_identity == entry.source_identity)
            .order_by(DebugRecord.created_at, DebugRecord.id)
        ).all()
        chosen = next((peer for peer in peers if peer.cache_state == "ready"), entry)
        hashes = {peer.sha256 for peer in peers if peer.sha256}
        conflict = len(hashes) > 1
        values = {key: getattr(chosen, key) for key in CACHE_FIELDS}
        values["sha256"] = chosen.sha256 or next(iter(hashes), None)
        if conflict:
            values.update(cache_state="failed", cache_error_code="SOURCE_CHANGED")
        cache = CacheRecord(
            source_identity=entry.source_identity,
            storage_key=chosen.id,
            file_name=chosen.file_name,
            platform=chosen.platform,
            size_bytes=chosen.size_bytes,
            **values,
            legacy_storage_keys=[
                str(peer.id)
                for peer in peers
                if (peer.id != chosen.id or conflict) and peer.cache_state == "ready"
            ],
        )
        db.add(cache)
        db.flush()
    if (
        cache.size_bytes != entry.size_bytes
        or cache.platform != entry.platform
        or cache.file_name != entry.file_name
    ):
        raise AppError(409, "SOURCE_CHANGED", "共享来源快照的文件身份不一致")
    _project_cache(db, cache)
    entry.cache_record = cache
    return cache


def mark_cache_failed(db, entry, code):
    key = int(digest(f"cache_execution:{entry.source_identity}")[:15], 16)
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}):
        # A newer source worker has already taken ownership; its outcome is authoritative.
        return
    cache = source_cache(db, entry)
    # A completed newer source attempt must not be downgraded by an older task's error handler.
    if cache.cache_state == "ready":
        return
    _project_cache(
        db, cache, cache_state="failed", cache_error_code=code, cache_updated_at=utcnow()
    )


def mark_cache_missing(db, entry):
    cache = source_cache(db, entry)
    _project_cache(
        db,
        cache,
        cache_state="missing",
        downloaded_bytes=0,
        cache_error_code=None,
        cache_updated_at=utcnow(),
    )


def touch_cache(db, entry):
    cache = source_cache(db, entry)
    _project_cache(db, cache, last_access_at=utcnow())


def cache_usage(db):
    # Legacy direct records are linked lazily; normal imports link immediately.
    for entry in db.scalars(select(DebugRecord).where(DebugRecord.cache_identity.is_(None))):
        source_cache(db, entry)
    rows = db.scalars(select(CacheRecord)).all()
    return {
        "used_bytes": sum(
            row.size_bytes * ((row.cache_state == "ready") + len(row.legacy_storage_keys))
            for row in rows
        ),
        "reserved_bytes": sum(
            row.size_bytes for row in rows if row.cache_state in {"downloading", "verifying"}
        ),
    }


def cache_settings(db):
    row = state(db, "cache", locked=True)
    if not row.revision:
        row.data, row.revision = dict(DEFAULT_CACHE), 1
    return row


def cache_root(settings):
    root = Path(settings.cache_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or not root.is_dir():
        raise AppError(503, "CACHE_PATH_INVALID", "缓存路径不可用")
    return root.resolve()


def cache_path(settings, entry):
    db = object_session(entry)
    cache = source_cache(db, entry) if db else entry.cache_record
    storage_key = cache.storage_key if cache else entry.id
    return cache_root(settings) / f"{UUID(str(storage_key))}.package"


def cache_status(row):
    return {
        "state": row.cache_state,
        "downloaded_bytes": row.downloaded_bytes,
        "total_bytes": row.size_bytes,
        "sha256": row.sha256,
        "error_code": row.cache_error_code,
        "error_message": "文件准备失败，请联系管理员或重试" if row.cache_error_code else None,
        "updated_at": row.cache_updated_at,
    }


def entry_dto(row, settings):
    names = (
        "id",
        "created_at",
        "updated_at",
        "revision",
        "app_id",
        "platform",
        "file_name",
        "size_bytes",
        "version_name",
        "build_number",
        "source_tag",
        "enabled",
        "source",
    )
    return {
        **{n: getattr(row, n) for n in names},
        "mode": "debug",
        "cache": cache_status(row),
        "version_label_source": "manual" if row.version_name else "tag",
        "page_url": settings.site_url + f"/debug/{row.id}",
    }


def catalog_app(db, app):
    count = db.scalar(
        select(func.count())
        .select_from(DebugRecord)
        .where(DebugRecord.app_id == app.id, DebugRecord.enabled.is_(True))
    )
    return {
        n: getattr(app, n) for n in ("id", "name", "public_slug", "description", "platforms")
    } | {"debug_entry_count": count}


def catalog_entry(db, row, settings):
    app = db.get(AppRecord, row.app_id)
    return {
        "id": row.id,
        "app": catalog_app(db, app),
        "mode": "debug",
        "platform": row.platform,
        "file_name": row.file_name,
        "size_bytes": row.size_bytes,
        "version_name": row.version_name,
        "build_number": row.build_number,
        "version_label": row.version_name or f"Tag: {row.source_tag}",
        "version_label_source": "manual" if row.version_name else "tag",
        "created_at": row.created_at,
        "cache": cache_status(row),
        "page_url": settings.site_url + f"/debug/{row.id}",
        "installation_notice": "IPA 下载不等于可以直接安装，请使用符合签名及设备要求的安装方式。"
        if row.platform == "ios"
        else None,
    }


def source_snapshot(repo, release, asset):
    return {
        "repository_id": str(repo["repository_id"]),
        "repository_full_name": repo["full_name"],
        "release_id": str(release["id"]),
        "asset_id": str(asset["id"]),
        "asset_updated_at": asset["updated_at"],
        "size_bytes": asset["size"],
        "digest": asset.get("digest"),
    }


def create_entries(db, app, payload, settings):
    repo = app.repository
    if not repo or not app.enabled:
        raise AppError(409, "APP_NOT_READY", "App 尚未绑定仓库或已停用")
    api = get_github_client(db, UUID(repo["connector_id"]), settings)
    try:
        repository = api.get_repository(repo["full_name"])
        if str(repository["id"]) != str(repo["repository_id"]):
            raise AppError(409, "SOURCE_CHANGED", "仓库身份已变化，请重新绑定")
        release = api.get_release(repo["full_name"], payload["release_id"])
        if release.get("draft"):
            raise AppError(422, "DRAFT_NOT_DISTRIBUTABLE", "草稿 Release 不可分发")
        assets = api.list_assets(repo["full_name"], payload["release_id"])
    finally:
        api.close()
    by_id = {str(a["id"]): a for a in assets}
    selections = payload["assets"]
    if len({s["asset_id"] for s in selections}) != len(selections):
        raise AppError(422, "DUPLICATE_ASSET", "同一请求不能重复选择附件")
    limit = cache_settings(db).data["max_file_bytes"]
    items, created = [], 0
    app = db.scalar(
        select(AppRecord)
        .where(AppRecord.id == app.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not app or not app.enabled or app.repository != repo:
        raise AppError(409, "APP_CHANGED", "App 配置已变化，请刷新后重新选择")
    lock(db, f"app_entries:{app.id}")
    for choice in selections:
        asset = by_id.get(choice["asset_id"])
        if not asset:
            raise AppError(422, "ASSET_NOT_IN_RELEASE", "附件不属于所选 Release")
        platform = (
            "android"
            if asset["name"].lower().endswith(".apk")
            else "ios"
            if asset["name"].lower().endswith(".ipa")
            else None
        )
        if platform is None or choice["platform"] != platform or platform not in app.platforms:
            raise AppError(422, "UNSUPPORTED_PACKAGE", "附件类型与 App 平台不匹配")
        if asset["size"] <= 0 or asset["size"] > limit:
            raise AppError(422, "FILE_SIZE_EXCEEDED", "文件大小超过当前缓存限制")
        snapshot = source_snapshot(repo, release, asset)
        identity = digest(snapshot)
        row = db.scalar(
            select(DebugRecord).where(
                DebugRecord.app_id == app.id, DebugRecord.source_identity == identity
            )
        )
        if row is None:
            now = utcnow()
            row = DebugRecord(
                app_id=app.id,
                connector_id=UUID(repo["connector_id"]),
                source_identity=identity,
                source=snapshot,
                platform=platform,
                file_name=asset["name"][:255],
                size_bytes=asset["size"],
                source_tag=release["tag_name"],
                version_name=choice.get("version_name"),
                build_number=choice.get("build_number"),
                enabled=payload["enabled"],
                revision=1,
                cache_state="missing",
                downloaded_bytes=0,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
            created += 1
        source_cache(db, row)
        items.append(row)
    return {
        "items": [entry_dto(r, settings) for r in items],
        "created_count": created,
        "existing_count": len(items) - created,
    }


def ensure_cache(db, entry):
    cache = source_cache(db, entry)
    if cache.cache_state in {"missing", "failed", "evicted"}:
        _project_cache(
            db, cache, cache_state="queued", cache_error_code=None, cache_updated_at=utcnow()
        )
    return enqueue(
        db,
        "cache_download",
        resource_id=str(entry.id),
        app_id=entry.app_id,
        dedupe_key=cache_lock_key(entry),
    )


def validate_package(path, platform):
    try:
        with zipfile.ZipFile(path) as package:
            names = package.namelist()
            valid = (
                "AndroidManifest.xml" in names
                if platform == "android"
                else any(re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", name) for name in names)
            )
            if not valid:
                raise AppError(422, "INVALID_PACKAGE", "附件缺少 APK / IPA 必需结构")
    except (zipfile.BadZipFile, OSError):
        raise AppError(422, "INVALID_PACKAGE", "附件不是有效的 APK / IPA 文件") from None


def check_source(api, entry):
    source = entry.source
    repository = api.get_repository(source["repository_full_name"])
    if str(repository["id"]) != source["repository_id"]:
        raise AppError(409, "SOURCE_CHANGED", "源仓库身份已变化")
    release = api.get_release(source["repository_full_name"], source["release_id"])
    if release.get("draft"):
        raise AppError(409, "SOURCE_NOT_AVAILABLE", "源 Release 已不可分发")
    asset = api.get_asset(source["repository_full_name"], source["asset_id"])
    ids = {
        str(a["id"]) for a in api.list_assets(source["repository_full_name"], source["release_id"])
    }
    if source["asset_id"] not in ids:
        raise AppError(409, "SOURCE_NOT_AVAILABLE", "源附件已移除")
    if (
        str(asset["id"]) != source["asset_id"]
        or asset["size"] != source["size_bytes"]
        or asset["updated_at"] != source["asset_updated_at"]
        or asset.get("digest") != source.get("digest")
        or asset["name"] != entry.file_name
    ):
        raise AppError(409, "SOURCE_CHANGED", "源附件发生变化，请重新选择")


def _source_client(db, entry, settings):
    # A disabled App does not revoke another App's independently authorized source binding.
    peers = db.scalars(
        select(DebugRecord)
        .join(AppRecord)
        .where(
            DebugRecord.source_identity == entry.source_identity,
            DebugRecord.enabled.is_(True),
            AppRecord.enabled.is_(True),
        )
        .order_by(DebugRecord.created_at, DebugRecord.id)
    ).all()
    peers.sort(key=lambda peer: peer.id != entry.id)
    last_error = AppError(409, "SOURCE_NOT_AVAILABLE", "没有启用的安装包来源")
    for peer in peers:
        api = None
        try:
            api = get_github_client(db, peer.connector_id, settings)
            check_source(api, peer)
            return api, peer
        except AppError as exc:
            if api:
                api.close()
            if exc.code == "SOURCE_CHANGED":
                raise
            last_error = exc
    raise last_error


def _verify_source_fence(fence, backend_pid):
    try:
        actual_pid = fence.scalar(text("SELECT pg_backend_pid()"))
        fence.commit()
        if actual_pid != backend_pid:
            raise AppError(503, "CACHE_WORKER_LEASE_LOST", "缓存执行连接已变化，请重试", True)
    except SQLAlchemyError:
        raise AppError(503, "CACHE_WORKER_LEASE_LOST", "缓存执行连接已中断，请重试", True) from None


def download_cache(db, settings, entry_id, task_id):
    entry = db.get(DebugRecord, entry_id)
    if entry is None:
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "安装包不存在")
    # Task-ID locking is insufficient when legacy/retry tasks address two entries of one source.
    key = int(digest(f"cache_execution:{entry.source_identity}")[:15], 16)
    with db.get_bind().connect() as fence:
        owned = fence.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        backend_pid = fence.scalar(text("SELECT pg_backend_pid()"))
        fence.commit()
        if not owned:
            raise RetryLater(5)
        try:
            _download_shared_cache(
                db, settings, entry, task_id, lambda: _verify_source_fence(fence, backend_pid)
            )
        finally:
            try:
                fence.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                fence.commit()
            except SQLAlchemyError:
                pass  # A dead connection already released its locks; retain the domain error.


def _download_shared_cache(db, settings, entry, task_id, verify_fence):
    lock(db, "cache_capacity")
    cfg = cache_settings(db).data
    cache = source_cache(db, entry)
    destination = cache_path(settings, entry)
    if cache.cache_state == "ready" and destination.is_file() and not destination.is_symlink():
        return
    rows = db.scalars(select(CacheRecord)).all()
    used = sum(
        r.size_bytes
        for r in rows
        if r.source_identity != cache.source_identity
        and r.cache_state in {"ready", "downloading", "verifying"}
    )
    used += sum(r.size_bytes * len(r.legacy_storage_keys) for r in rows)
    active = sum(
        r.cache_state in {"downloading", "verifying"} and r.source_identity != cache.source_identity
        for r in rows
    )
    if active >= cfg["download_concurrency"]:
        raise RetryLater(5)
    if cache.size_bytes > cfg["max_file_bytes"] or used + cache.size_bytes > cfg["budget_bytes"]:
        raise AppError(409, "CACHE_CAPACITY_EXCEEDED", "缓存配额不足，请清理空间")
    if shutil.disk_usage(cache_root(settings)).free < cache.size_bytes + 64 * 1024 * 1024:
        raise AppError(409, "CACHE_DISK_FULL", "磁盘剩余空间不足")
    _project_cache(
        db, cache, cache_state="downloading", downloaded_bytes=0, cache_updated_at=utcnow()
    )
    db.commit()
    temporary = cache_root(settings) / f"{UUID(str(cache.storage_key))}.{UUID(str(task_id))}.part"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    api = None
    try:
        api, source_entry = _source_client(db, entry, settings)
        last = utcnow()

        def progress(size):
            nonlocal last
            if (utcnow() - last).total_seconds() >= 1:
                verify_fence()
                lock(db, cache_lock_key(entry))
                _project_cache(db, cache, downloaded_bytes=size, cache_updated_at=utcnow())
                db.commit()
                last = utcnow()

        result = api.download_asset(
            source_entry.source["repository_full_name"],
            source_entry.source["asset_id"],
            temporary,
            cache.size_bytes,
            progress=progress,
        )
        lock(db, cache_lock_key(entry))
        _project_cache(db, cache, cache_state="verifying", cache_updated_at=utcnow())
        db.commit()
        if result["size_bytes"] != cache.size_bytes:
            raise AppError(409, "SOURCE_CHANGED", "源文件大小不一致")
        if cache.sha256 and result["sha256"] != cache.sha256:
            raise AppError(409, "SOURCE_CHANGED", "重建缓存内容与首次下载不一致")
        expected = source_entry.source.get("digest")
        if expected and (not expected.startswith("sha256:") or result["sha256"] != expected[7:]):
            raise AppError(409, "SOURCE_CHANGED", "源文件摘要不一致")
        validate_package(temporary, cache.platform)
        check_source(api, source_entry)
        with temporary.open("rb") as file:
            os.fsync(file.fileno())
        lock(db, cache_lock_key(entry))
        verify_fence()
        os.replace(temporary, destination)
        cache.legacy_storage_keys = [
            key for key in cache.legacy_storage_keys if key != str(cache.storage_key)
        ]
        _project_cache(
            db,
            cache,
            cache_state="ready",
            sha256=result["sha256"],
            downloaded_bytes=cache.size_bytes,
            cache_error_code=None,
            last_access_at=utcnow(),
            cache_updated_at=utcnow(),
        )
        db.commit()
    except OSError as exc:
        code = "CACHE_DISK_FULL" if exc.errno in {errno.ENOSPC, errno.EDQUOT} else "CACHE_IO_ERROR"
        raise AppError(503, code, "本地缓存写入失败") from None
    finally:
        if api:
            api.close()
        temporary.unlink(missing_ok=True)


def cleanup_cache(db, settings, scope="expired"):
    lock(db, "cache_capacity")
    cfg, now = cache_settings(db).data, utcnow()
    cache_usage(db)
    rows = db.scalars(select(CacheRecord)).all()
    for cache in rows:
        lock(db, f"cache_source:{cache.source_identity}")
        db.refresh(cache)
        if cache.cache_state in {"queued", "downloading", "verifying"}:
            continue
        peers = select(DebugRecord.id).where(DebugRecord.source_identity == cache.source_identity)
        protected = db.scalar(
            select(GrantRecord.token_hash)
            .where(GrantRecord.entry_id.in_(peers), GrantRecord.expires_at > now)
            .limit(1)
        )
        active = db.scalar(
            select(TransferLease.id)
            .where(TransferLease.entry_id.in_(peers), TransferLease.expires_at > now)
            .limit(1)
        )
        if protected or active:
            continue
        # Backfilled duplicate files stay budgeted until no grant/lease protects their source.
        for storage_key in cache.legacy_storage_keys:
            (cache_root(settings) / f"{UUID(str(storage_key))}.package").unlink(missing_ok=True)
        cache.legacy_storage_keys = []
        if cache.cache_state != "ready":
            continue
        if (
            scope == "expired"
            and cache.last_access_at
            and cache.last_access_at > now - timedelta(seconds=cfg["idle_ttl_seconds"])
        ):
            continue
        (cache_root(settings) / f"{UUID(str(cache.storage_key))}.package").unlink(missing_ok=True)
        _project_cache(db, cache, cache_state="evicted", cache_updated_at=now, downloaded_bytes=0)
    db.commit()
