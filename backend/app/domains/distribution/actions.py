"""CI rule validation and resumable, provider-verified build processing."""

import fnmatch
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from app.api.contracts import ActionsRule, BuildEvent
from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.applications.service import platform_enabled
from app.domains.auth.service import utcnow
from app.domains.distribution.feishu import create_delivery, delivery_dto, validate_chats
from app.domains.distribution.models import DebugRecord, DeliveryRecord, EventRecord, RuleRecord
from app.domains.distribution.package_metadata import notification_build_number
from app.domains.distribution.service import RetryLater, lock, must_get
from app.domains.github.service import get_github_client

RULE_FIELDS = (
    "name",
    "workflow_path",
    "allowed_branches",
    "allowed_tags",
    "asset_patterns",
    "chat_ids",
    "enabled",
    "repository_id",
    "repository_full_name",
)


def recent_admin(context):
    when = context.session.authenticated_at
    if when is None or when + timedelta(minutes=10) <= utcnow():
        raise AppError(403, "RECENT_AUTH_REQUIRED", "此操作需要最近十分钟内重新登录管理员")


def validate_rule(db, data):
    if not data.get("name", "").strip():
        raise AppError(422, "RULE_NAME_INVALID", "规则名称不能为空")
    if not data.get("allowed_branches") and not data.get("allowed_tags"):
        raise AppError(422, "TRUSTED_REF_REQUIRED", "至少配置一个可信分支或 Tag")
    for group in ("allowed_branches", "allowed_tags", "asset_patterns"):
        patterns = data.get(group, [])
        if len(patterns) != len(set(patterns)):
            raise AppError(422, "PATTERN_INVALID", "匹配规则不能重复")
        for pattern in patterns:
            if not pattern.strip() or any(ord(c) < 32 for c in pattern):
                raise AppError(422, "PATTERN_INVALID", "匹配规则含无效字符")
    if data.get("enabled"):
        data["chat_ids"] = validate_chats(db, data["chat_ids"])
    else:
        data["chat_ids"] = list(dict.fromkeys(data["chat_ids"]))


def rule_dto(row, settings):
    return ActionsRule(
        id=row.id,
        app_id=row.app_id,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
        **{name: row.data[name] for name in RULE_FIELDS},
        mode="debug",
        has_token=bool(row.token_hash),
        token_created_at=row.token_created_at,
        callback_url=f"{settings.site_url}/api/v1/integrations/github-actions/{row.id}/events",
    )


def stages_initial():
    return [
        {
            "name": name,
            "state": "pending",
            "error_code": None,
            "error_message": None,
            "started_at": None,
            "finished_at": None,
        }
        for name in ("verify", "wait_run", "cache", "notify")
    ]


def stage(event, name, status, error=None):
    rows = [dict(item) for item in event.stages]
    for item in rows:
        if item["name"] == name:
            item["state"] = status
            if not item["started_at"]:
                item["started_at"] = utcnow().isoformat()
            item["finished_at"] = (
                utcnow().isoformat() if status not in {"running", "pending"} else None
            )
            item["error_code"] = error.code if error else None
            item["error_message"] = error.message if error else None
    event.stages, event.updated_at = rows, utcnow()


def event_dto(db, row):
    deliveries = db.scalars(
        select(DeliveryRecord)
        .where(DeliveryRecord.event_id == row.id)
        .order_by(DeliveryRecord.created_at, DeliveryRecord.id)
    ).all()
    retryable = [s["name"] for s in row.stages if s["state"] in {"failed", "partial_success"}]
    if row.state not in {"failed", "partial_success", "unknown"}:
        retryable = []
    if any(d.state == "unknown" for d in deliveries):
        retryable = [name for name in retryable if name != "notify"]
    return BuildEvent(
        id=row.id,
        app_id=row.app_id,
        rule_id=row.rule_id,
        **{
            name: row.data[name]
            for name in ("repository_id", "run_id", "run_attempt", "head_sha", "release_id")
        },
        state=row.state,
        stages=row.stages,
        assets=row.assets,
        deliveries=[delivery_dto(d) for d in deliveries],
        retryable_stages=retryable,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def active_rule(db, event):
    from app.domains.access.task_authorization import check_task_authorization

    check_task_authorization(db)
    rule = must_get(db, RuleRecord, event.rule_id)
    app = must_get(db, AppRecord, event.app_id)
    if not rule.data.get("enabled") or not rule.token_hash or not app.enabled:
        raise AppError(409, "RULE_DISABLED", "规则令牌已撤销、规则或 App 已停用")
    binding = app.repository
    if not binding or any(
        binding.get(k) != event.rule_snapshot.get(k) for k in ("repository_id", "connector_id")
    ):
        raise AppError(409, "SOURCE_CHANGED", "App 仓库关联已变化")
    return rule, app


def verify_source(client, event):
    try:
        return _verify_source(client, event)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AppError(503, "PROVIDER_INVALID_RESPONSE", "GitHub 构建元数据不完整") from None


def _verify_source(client, event):
    data, rule = event.data, event.rule_snapshot
    name = rule["repository_full_name"]
    repository = client.get_repository(name)
    run = client.get_run(name, data["run_id"], data["run_attempt"])
    if (
        str(repository.get("id")) != data["repository_id"]
        or str(run.get("id")) != data["run_id"]
        or run.get("run_attempt") != data["run_attempt"]
        or run.get("head_sha") != data["head_sha"]
        or str(run.get("repository", {}).get("id")) != data["repository_id"]
        or str(run.get("head_repository", {}).get("id")) != data["repository_id"]
        or run.get("event") not in {"push", "workflow_dispatch", "release", "schedule"}
        or run.get("pull_requests")
    ):
        raise AppError(403, "UNTRUSTED_WORKFLOW_RUN", "构建身份、来源仓库或触发方式不可信")
    workflow = client.get_workflow(name, run.get("workflow_id"))
    if (
        workflow.get("path") != rule["workflow_path"]
        or run.get("path", "").split("@")[0] != rule["workflow_path"]
    ):
        raise AppError(403, "UNTRUSTED_WORKFLOW", "构建工作流与规则不匹配")
    release = client.get_release(name, data["release_id"])
    if str(release.get("id")) != data["release_id"] or release.get("draft"):
        raise AppError(403, "UNTRUSTED_RELEASE", "Release 不存在、身份不符或仍为草稿")
    tag = release.get("tag_name", "")
    if client.tag_commit(name, tag) != data["head_sha"]:
        raise AppError(403, "TAG_COMMIT_MISMATCH", "Release Tag 与构建提交不一致")
    branch = run.get("head_branch", "")
    branch_allowed = any(fnmatch.fnmatchcase(branch, p) for p in rule["allowed_branches"])
    tag_allowed = (branch == tag or run.get("event") == "release") and any(
        fnmatch.fnmatchcase(tag, p) for p in rule["allowed_tags"]
    )
    if not (branch_allowed or tag_allowed):
        raise AppError(403, "UNTRUSTED_REF", "构建分支或 Tag 不在允许范围")
    assets = {str(asset.get("id")): asset for asset in release.get("assets", [])}
    chosen = []
    for asset_id in data["asset_ids"]:
        asset = assets.get(asset_id)
        if not asset or not any(
            fnmatch.fnmatchcase(asset.get("name", ""), p) for p in rule["asset_patterns"]
        ):
            raise AppError(403, "UNTRUSTED_ASSET", "附件不属于 Release 或不匹配安装包规则")
        if asset["name"].rsplit(".", 1)[-1].lower() not in {"apk", "ipa"}:
            raise AppError(422, "UNSUPPORTED_ASSET", "M1 仅接收 APK 或 IPA 安装包")
        chosen.append(asset)
    return run, release, chosen


def process_event(db, settings, event_id):
    from app.domains.access.task_authorization import check_task_authorization
    from app.domains.distribution.packages import (
        create_verified_entries,
        ensure_cache,
        fetch_import_source,
    )

    event_id = UUID(str(event_id))

    def lock_event():
        check_task_authorization(db)
        current = must_get(db, EventRecord, event_id)
        db.scalar(select(AppRecord).where(AppRecord.id == current.app_id).with_for_update())
        lock(db, f"event:{event_id}")
        db.refresh(current)
        return current

    event = lock_event()
    if event.state in {"succeeded", "partial_success", "failed", "unknown"}:
        return
    current_stage = "verify"
    try:
        rule, app = active_rule(db, event)
        stage(event, "verify", "running")
        event.state = "verifying"
        db.commit()  # Release App and role locks across GitHub network requests.
        with get_github_client(db, event.rule_snapshot["connector_id"], settings) as client:
            run, release, chosen = verify_source(client, event)
        if run.get("status") == "completed" and run.get("conclusion") == "success":
            repo, import_release, import_assets = fetch_import_source(
                db, app, event.data["release_id"], settings
            )
        event = lock_event()
        rule, app = active_rule(db, event)
        stage(event, "verify", "succeeded")
        current_stage = "wait_run"
        if run.get("status") != "completed":
            if event.created_at + timedelta(hours=6) < utcnow():
                raise AppError(409, "WORKFLOW_TIMEOUT", "构建超过六小时仍未结束")
            event.state = "waiting_run"
            stage(event, "wait_run", "running")
            db.commit()
            raise RetryLater(delay=15)
        if run.get("conclusion") != "success":
            raise AppError(409, "WORKFLOW_NOT_SUCCESSFUL", "GitHub 工作流未成功完成")
        stage(event, "wait_run", "succeeded")
        current_stage = "cache"
        event.state = "caching"
        stage(event, "cache", "running")
        # Revalidate administrative revocation after provider I/O.
        db.refresh(rule)
        db.refresh(app)
        active_rule(db, event)
        results = {item["asset_id"]: dict(item) for item in event.assets}
        for asset in chosen:
            asset_id = str(asset["id"])
            result = results[asset_id]
            if result["state"] == "failed":
                continue
            if result.get("entry_id"):
                entry = db.get(DebugRecord, UUID(result["entry_id"]))
            else:
                try:
                    batch = create_verified_entries(
                        db,
                        app,
                        {
                            "release_id": event.data["release_id"],
                            "enabled": True,
                            "assets": [
                                {
                                    "asset_id": asset_id,
                                    "platform": "android"
                                    if asset["name"].lower().endswith(".apk")
                                    else "ios",
                                }
                            ],
                        },
                        settings,
                        repo,
                        import_release,
                        import_assets,
                    )
                    entry = db.get(DebugRecord, UUID(str(batch["items"][0]["id"])))
                    result["entry_id"] = str(entry.id)
                    result["file_name"] = entry.file_name
                except AppError as exc:
                    result.update(state="failed", error_code=exc.code, file_name=asset["name"])
                    continue
            if entry is None or not entry.enabled or not platform_enabled(app, entry.platform):
                result.update(state="failed", error_code="RESOURCE_NOT_AVAILABLE")
            elif entry.cache_state == "ready":
                result.update(state="ready", error_code=None)
            elif entry.cache_state == "failed":
                result.update(state="failed", error_code=entry.cache_error_code)
            else:
                ensure_cache(db, entry)
                result.update(state="caching", error_code=None)
        event.assets = list(results.values())
        db.commit()
        if any(item["state"] in {"pending", "caching"} for item in event.assets):
            raise RetryLater(delay=5)
        event = lock_event()
        rule, app = active_rule(db, event)
        ready = [item for item in event.assets if item["state"] == "ready"]
        partial = len(ready) != len(event.assets)
        stage(
            event,
            "cache",
            "partial_success" if ready and partial else "succeeded" if ready else "failed",
        )
        current_stage = "notify"
        event.state = "notifying"
        stage(event, "notify", "running")
        deliveries = db.scalars(
            select(DeliveryRecord).where(DeliveryRecord.event_id == event.id)
        ).all()
        if not deliveries:
            numbers, metadata_pending = [], False
            started_at = next(s["started_at"] for s in event.stages if s["name"] == "notify")
            for item in ready:
                entry = db.get(DebugRecord, UUID(item["entry_id"]))
                number, pending = notification_build_number(
                    db, settings, entry, event.id, started_at
                )
                numbers.append((item["file_name"], number or "未获取"))
                metadata_pending = metadata_pending or pending
            if metadata_pending:
                db.commit()
                raise RetryLater(delay=5)
            # Different platform builds must remain associated with their own file names.
            unique_numbers = list(dict.fromkeys(number for _, number in numbers))
            build_number = (
                unique_numbers[0]
                if len(unique_numbers) == 1
                else "\n".join(f"{name}：{number}" for name, number in numbers) or None
            )
            result = "partial_failure" if ready and partial else "success" if ready else "failure"
            card = {
                "title": "Debug 安装包已就绪" if ready else "构建成功，安装包准备失败",
                "summary": f"已就绪 {len(ready)}/{len(event.assets)} 个安装包",
                "app_name": app.name,
                "mode": "debug",
                "version_label": f"Tag: {release['tag_name']}",
                "build_number": build_number,
                "file_names": [r["file_name"] for r in ready],
                "result": result,
                "occurred_at": utcnow().isoformat(),
                "page_url": f"{settings.site_url}/apps/{app.id}" if ready else None,
            }
            for chat_id in event.rule_snapshot["chat_ids"]:
                deliveries.append(
                    create_delivery(
                        db,
                        chat_id,
                        card,
                        event_id=event.id,
                        app_id=app.id,
                        kind="build_partial"
                        if ready and partial
                        else "build_ready"
                        if ready
                        else "build_failed",
                    )
                )
            db.commit()
        if any(d.state in {"queued", "sending"} for d in deliveries):
            raise RetryLater(delay=5)
        if any(d.state == "unknown" for d in deliveries):
            stage(event, "notify", "unknown")
            event.state = "unknown"
        elif any(d.state == "failed" for d in deliveries):
            stage(event, "notify", "failed")
            event.state = "partial_success" if ready else "failed"
        else:
            stage(event, "notify", "succeeded")
            event.state = (
                "partial_success" if ready and partial else "succeeded" if ready else "failed"
            )
        db.commit()
    except AppError as exc:
        event.state = "failed"
        stage(event, current_stage, "failed", exc)
        # Only verified builds may trigger a failure notification; untrusted callbacks cannot spam.
        if current_stage == "wait_run" and not db.scalar(
            select(DeliveryRecord.id).where(DeliveryRecord.event_id == event.id).limit(1)
        ):
            card = {
                "title": "GitHub 构建未成功完成",
                "summary": exc.message,
                "app_name": app.name,
                "mode": "debug",
                "version_label": None,
                "file_names": [],
                "result": "failure",
                "occurred_at": utcnow().isoformat(),
                "page_url": None,
            }
            for chat_id in event.rule_snapshot["chat_ids"]:
                create_delivery(
                    db, chat_id, card, event_id=event.id, app_id=app.id, kind="build_failed"
                )
        db.commit()
        raise
