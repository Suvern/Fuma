"""Opt-in Release polling and rule-based imports using the complete provider snapshot."""

from datetime import datetime, timedelta
from fnmatch import fnmatchcase
from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.audit.service import record_audit
from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord, TaskRecord
from app.domains.distribution.service import digest, enqueue, lock
from app.domains.github.models import GithubConnector, GithubReleasePolicy, GithubRepositorySync

DEFAULT_RULES = {
    "asset_patterns": ["*.apk", "*.ipa"],
    "exclude_patterns": [],
    "tag_pattern": "*",
    "prerelease": "all",
}


def validate_rules(rules):
    for pattern in [rules["tag_pattern"], *rules["asset_patterns"], *rules["exclude_patterns"]]:
        if not pattern.strip() or any(ord(char) < 32 for char in pattern):
            raise AppError(422, "INVALID_RELEASE_RULE", "匹配规则不能为空或包含控制字符")
    return rules


def policy_dto(db, app):
    row = db.get(GithubReleasePolicy, app.id)
    status = "disabled"
    if row and row.auto_enabled:
        connector = (
            db.get(GithubConnector, UUID(app.repository["connector_id"]))
            if app.repository
            else None
        )
        task = db.get(TaskRecord, row.last_task_id) if row.last_task_id else None
        status = (
            "paused"
            if not app.enabled or not connector or not connector.enabled
            else "running"
            if task and task.state in {"queued", "running"}
            else "failed"
            if task and task.state in {"failed", "partial_success"}
            else "scheduled"
        )
    return {
        "rules": row.settings if row else DEFAULT_RULES,
        "auto_enabled": row.auto_enabled if row else False,
        "interval_minutes": row.interval_minutes if row else 15,
        "revision": row.revision if row else 0,
        "next_check_at": row.next_check_at if row and status != "paused" else None,
        "last_task_id": row.last_task_id if row else None,
        "last_result": row.last_result if row else None,
        "status": status,
    }


def get_policy(db, app_id):
    lock(db, f"release-policy:{app_id}")
    row = db.get(GithubReleasePolicy, app_id, populate_existing=True)
    if row is None:
        row = GithubReleasePolicy(
            app_id=app_id,
            revision=0,
            settings=DEFAULT_RULES.copy(),
            auto_enabled=False,
            interval_minutes=15,
        )
        db.add(row)
        db.flush()
    return row


def source_key(source):
    stamp = datetime.fromisoformat(source["asset_updated_at"].replace("Z", "+00:00"))
    return (
        str(source["repository_id"]),
        str(source["release_id"]),
        str(source["asset_id"]),
        stamp,
        source["size_bytes"],
        source.get("digest"),
    )


def asset_source(binding, release, asset):
    return {
        "repository_id": binding["repository_id"],
        "release_id": release["id"],
        "asset_id": asset["id"],
        "asset_updated_at": asset["updated_at"],
        "size_bytes": asset["size_bytes"],
        "digest": asset.get("digest"),
    }


def match_snapshot(db, app, rules):
    from app.domains.distribution.packages import cache_settings

    validate_rules(rules)
    if not app.repository or not app.enabled:
        raise AppError(409, "APP_NOT_READY", "请先启用应用并关联 GitHub 仓库")
    snapshot = db.get(GithubRepositorySync, app.id)
    if not snapshot or snapshot.synced_at is None:
        raise AppError(409, "RELEASE_SNAPSHOT_REQUIRED", "请先同步 Releases，再预览匹配规则")
    known = {
        source_key(entry.source)
        for entry in db.scalars(select(DebugRecord).where(DebugRecord.app_id == app.id))
    }
    max_size = cache_settings(db).data["max_file_bytes"]
    matches, skipped = [], 0
    for release in snapshot.releases:
        release_matches = (
            not release["draft"]
            and fnmatchcase(release["tag_name"], rules["tag_pattern"])
            and (
                rules["prerelease"] == "all"
                or release["prerelease"] == (rules["prerelease"] == "only")
            )
        )
        for asset in release["assets"]:
            if not (
                release_matches
                and asset["supported"]
                and asset["platform"] in app.platforms
                and 0 < asset["size_bytes"] <= max_size
                and any(fnmatchcase(asset["name"], p) for p in rules["asset_patterns"])
                and not any(fnmatchcase(asset["name"], p) for p in rules["exclude_patterns"])
            ):
                skipped += 1
                continue
            source = asset_source(app.repository, release, asset)
            matches.append(
                {
                    "release_id": release["id"],
                    "tag_name": release["tag_name"],
                    "asset_id": asset["id"],
                    "file_name": asset["name"],
                    "platform": asset["platform"],
                    "size_bytes": asset["size_bytes"],
                    "existing": source_key(source) in known,
                    "source": source,
                }
            )
    token = digest({"binding": app.repository, "releases": snapshot.releases, "rules": rules})
    return snapshot, matches, skipped, token


def preview_import(db, app, rules):
    snapshot, matches, skipped, token = match_snapshot(db, app, rules)
    existing = sum(item["existing"] for item in matches)
    return {
        "snapshot_token": token,
        "synced_at": snapshot.synced_at,
        "matched_count": len(matches),
        "new_count": len(matches) - existing,
        "existing_count": existing,
        "skipped_count": skipped,
        "items": [{k: v for k, v in m.items() if k != "source"} for m in matches[:200]],
        "truncated": len(matches) > 200,
    }


def schedule_release_checks(db, now):
    # The scheduler owns this transaction lock until enqueue and the next due time commit together.
    lock(db, "release-poll-scheduler")
    policies = db.scalars(
        select(GithubReleasePolicy).where(
            GithubReleasePolicy.auto_enabled.is_(True),
            GithubReleasePolicy.next_check_at <= now,
        )
    ).all()
    for row in policies:
        row = get_policy(db, row.app_id)
        if not row.auto_enabled or not row.next_check_at or row.next_check_at > now:
            continue
        app = db.get(AppRecord, row.app_id)
        connector = (
            db.get(GithubConnector, UUID(app.repository["connector_id"]))
            if app and app.repository
            else None
        )
        if not app or not app.enabled or not connector or not connector.enabled:
            continue
        task = enqueue(
            db,
            "release_sync",
            app_id=app.id,
            resource_id=str(app.id),
            payload={"policy_revision": row.revision},
            dedupe_key=f"release_sync:{app.id}",
        )
        row.last_task_id = task.id
        row.next_check_at = now + timedelta(minutes=row.interval_minutes)


def check_automatic_policy(db, task):
    revision = task.payload.get("policy_revision")
    if revision is None:
        return
    row = db.get(GithubReleasePolicy, task.app_id, populate_existing=True)
    if not row or not row.auto_enabled or row.revision != revision:
        raise AppError(409, "RELEASE_POLICY_CHANGED", "自动同步规则已修改或停用，本次任务已停止")


def import_matches(db, settings, task, matches, binding):
    from app.domains.distribution.packages import create_verified_entries, fetch_import_source

    grouped = {}
    for match in matches:
        grouped.setdefault(match["release_id"], []).append(match)
    completed = task.payload.get("completed", {})
    result = {
        "checked_at": utcnow().isoformat(),
        "created_count": sum(v["created_count"] for v in completed.values()),
        "existing_count": sum(v["existing_count"] for v in completed.values()),
        "failed_count": 0,
        "errors": [],
    }
    fatal = {
        "RELEASE_POLICY_CHANGED",
        "SOURCE_CHANGED",
        "APP_CHANGED",
        "CONNECTOR_DISABLED",
        "GITHUB_BAD_CREDENTIAL",
        "GITHUB_RATE_LIMITED",
    }
    for release_id, selected in grouped.items():
        selected = [m for m in selected if digest(m["source"]) not in completed]
        if not selected:
            continue
        succeeded, errors = {}, []
        try:
            check_automatic_policy(db, task)
            app = db.get(AppRecord, task.app_id, populate_existing=True)
            if not app or not app.enabled or app.repository != binding:
                raise AppError(409, "SOURCE_CHANGED", "应用或仓库来源已变化，本次导入已停止")
            if "policy_revision" in task.payload:
                lock(db, f"release-policy:{app.id}")
                check_automatic_policy(db, task)
            known = {
                source_key(e.source)
                for e in db.scalars(select(DebugRecord).where(DebugRecord.app_id == app.id))
            }
            pending = [m for m in selected if source_key(m["source"]) not in known]
            for match in selected:
                if source_key(match["source"]) in known:
                    succeeded[digest(match["source"])] = {"created_count": 0, "existing_count": 1}
            if pending:
                repo, release, assets = fetch_import_source(db, app, release_id, settings)
                for match in pending:
                    try:
                        with db.begin_nested():
                            outcome = create_verified_entries(
                                db,
                                app,
                                {
                                    "release_id": release_id,
                                    "enabled": True,
                                    "assets": [
                                        {
                                            "asset_id": match["asset_id"],
                                            "platform": match["platform"],
                                        }
                                    ],
                                    "expected_assets": {match["asset_id"]: match},
                                },
                                settings,
                                repo,
                                release,
                                assets,
                            )
                            succeeded[digest(match["source"])] = {
                                k: outcome[k] for k in ("created_count", "existing_count")
                            }
                    except AppError as exc:
                        if exc.code in fatal:
                            raise
                        errors.append({"tag_name": match["tag_name"], "error_code": exc.code})
            count = sum(v["created_count"] for v in succeeded.values())
            record_audit(
                db,
                action="github.releases.import",
                resource_type="app",
                resource_id=str(app.id),
                actor_kind="system",
                request_id=str(task.id),
                summary=f"按规则导入 Release：新增 {count} 个，失败 {len(errors)} 个",
            )
            completed = {**completed, **succeeded}
            task.payload = {**task.payload, "completed": completed}
            task.progress = int(len(completed) / max(len(matches), 1) * 100)
            db.commit()
        except AppError as exc:
            db.rollback()
            if exc.code in fatal:
                raise
            succeeded = {}
            errors = [{"tag_name": m["tag_name"], "error_code": exc.code} for m in selected]
        result["created_count"] += sum(v["created_count"] for v in succeeded.values())
        result["existing_count"] += sum(v["existing_count"] for v in succeeded.values())
        result["failed_count"] += len(errors)
        result["errors"] = (result["errors"] + errors)[:100]
    task.payload = {**task.payload, "result": result}
    policy = get_policy(db, task.app_id)
    if policy.last_task_id == task.id:
        policy.last_result = result
    db.commit()
    return result


def execute_release_task(db, settings, task):
    from app.domains.github.service import sync_releases

    check_automatic_policy(db, task)
    if task.kind == "release_sync":
        sync_releases(db, task.app_id, settings)
        if "policy_revision" not in task.payload:
            return
        check_automatic_policy(db, task)
        policy = db.get(GithubReleasePolicy, task.app_id)
        app = db.get(AppRecord, task.app_id)
        _, matches, _, _ = match_snapshot(db, app, policy.settings)
        task.payload = {**task.payload, "matches": matches, "binding": app.repository}
        db.commit()
    import_matches(db, settings, task, task.payload["matches"], task.payload["binding"])
