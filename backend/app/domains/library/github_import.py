"""Fetch immutable GitHub snapshots into the same isolated parsing protocol as uploads."""

import hashlib
from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord
from app.domains.distribution.service import must_get
from app.domains.github.service import get_github_client
from app.domains.library.models import PublicationPackage, PublicationRecord, VersionRecord


def prepare(db, settings, upload, task):
    from app.api.library import active_app, upload_dir

    source = upload.source_snapshot
    app = active_app(db, upload.app_id)
    if app.repository != source["repository"]:
        raise AppError(409, "SOURCE_CHANGED", "导入期间仓库关联已变化")
    directory = upload_dir(settings, upload.id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "1"
    asset = source["asset"]
    binding = source["repository"]
    with get_github_client(db, binding["connector_id"], settings) as client:
        repository = client.get_repository(binding["full_name"])
        release = client.get_release(binding["full_name"], source["release_id"])
        current = next((a for a in release.get("assets", []) if str(a["id"]) == asset["id"]), None)
        if (
            str(repository["id"]) != binding["repository_id"]
            or release.get("draft")
            or not current
            or any(
                current.get(key) != expected
                for key, expected in [
                    ("name", asset["name"]),
                    ("size", asset["size_bytes"]),
                    ("updated_at", asset["updated_at"]),
                    ("digest", asset.get("digest")),
                ]
            )
        ):
            raise AppError(409, "SOURCE_CHANGED", "GitHub 来源内容已改变，请重新同步并确认")
        if not path.is_file():
            client.download_asset(binding["full_name"], asset["id"], path, asset["size_bytes"])
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    if path.stat().st_size != asset["size_bytes"] or (
        asset.get("digest") and asset["digest"] != "sha256:" + sha
    ):
        path.unlink(missing_ok=True)
        raise AppError(409, "SOURCE_CHANGED", "GitHub 来源长度或 SHA-256 不一致")
    upload.parts = [{"part_number": 1, "size_bytes": asset["size_bytes"], "sha256": sha}]
    upload.expected_parts, upload.chunk_size = 1, asset["size_bytes"]
    db.commit()


def link_result(db, upload, package):
    source = upload.source_snapshot
    if not source:
        return
    if source.get("version_id"):
        version = must_get(db, VersionRecord, UUID(source["version_id"]))
        existing = db.scalar(
            select(PublicationRecord.id)
            .join(PublicationPackage)
            .where(
                PublicationRecord.version_id == version.id,
                PublicationPackage.package_id == package.id,
            )
        )
        if not existing:
            publication = PublicationRecord(
                app_id=upload.app_id,
                version_id=version.id,
                platform=upload.platform,
                mode=upload.mode,
                created_at=utcnow(),
            )
            db.add(publication)
            db.flush()
            db.add(PublicationPackage(publication_id=publication.id, package_id=package.id))
    if source.get("legacy_entry_id"):
        from app.domains.storage.service import canonical

        if not package.storage_location_id:
            raise AppError(409, "STORAGE_NOT_READY", "旧条目仅在私有云原件就绪后才能切换")
        canonical(db, package)
        legacy = must_get(db, DebugRecord, UUID(source["legacy_entry_id"]))
        if legacy.sha256 and legacy.sha256 != package.sha256:
            raise AppError(
                409, "SOURCE_CHANGED", "旧条目已记录的 SHA-256 与新下载内容不同；保持旧下载入口"
            )
        legacy.persistent_package_id = package.id
        legacy.revision += 1
