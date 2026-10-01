"""Administrator Actions rules and strictly scoped CI bearer callbacks."""

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select

from app.api.applications import get_app
from app.api.contracts import (
    ActionsRule,
    ActionsRuleCreate,
    ActionsRuleCreated,
    ActionsRulePage,
    ActionsRuleUpdate,
    ActionsToken,
    BuildEvent,
    BuildEventAccepted,
    BuildEventPage,
    BuildEventRequest,
    BuildRetryRequest,
    TaskAccepted,
)
from app.api.dependencies import DB, Admin, require_admin, require_csrf, require_revision
from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.audit.service import record_audit
from app.domains.auth.service import token_hash, utcnow
from app.domains.distribution.actions import (
    active_rule,
    event_dto,
    recent_admin,
    rule_dto,
    stages_initial,
    validate_rule,
)
from app.domains.distribution.models import DebugRecord, DeliveryRecord, EventRecord, RuleRecord
from app.domains.distribution.service import (
    digest,
    enqueue,
    idem_begin,
    idem_save,
    lock,
    must_get,
    page,
    task_accepted,
)

router = APIRouter(tags=["actions"])
WRITE = [Depends(require_admin), Depends(require_csrf)]
READ = [Depends(require_admin)]


def audit(db, request, actor, action, resource_id, *, kind="admin"):
    record_audit(
        db,
        action=action,
        resource_type="actions",
        resource_id=str(resource_id),
        request_id=request.state.request_id,
        actor_kind=kind,
        actor_id=str(actor.user.id) if actor else None,
    )


def rule_locked(db, id, if_match):
    lock(db, f"rule:{id}")
    row = must_get(db, RuleRecord, id)
    require_revision(if_match, row.revision)
    return row


def mutate_rule(row):
    row.revision, row.updated_at = row.revision + 1, utcnow()


@router.get(
    "/apps/{id}/actions-rules",
    response_model=ActionsRulePage,
    operation_id="list_actions_rules",
    dependencies=READ,
)
def list_rules(
    id: UUID,
    request: Request,
    db: DB,
    page_number: int = Query(1, alias="page", ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
):
    must_get(db, AppRecord, id)
    rows = db.scalars(
        select(RuleRecord)
        .where(RuleRecord.app_id == id)
        .order_by(RuleRecord.created_at.desc(), RuleRecord.id)
    ).all()
    items = [
        rule_dto(row, request.app.state.settings)
        for row in rows
        if not q or q.casefold() in row.data["name"].casefold()
    ]
    return page(items, page_number, page_size)


@router.post(
    "/apps/{id}/actions-rules",
    response_model=ActionsRuleCreated,
    status_code=201,
    operation_id="create_actions_rule",
    dependencies=WRITE,
)
def create_rule(
    id: UUID, body: ActionsRuleCreate, request: Request, response: Response, db: DB, context: Admin
):
    recent_admin(context)
    app = get_app(db, id, lock=True)
    lock(db, f"app_entries:{id}")
    if not app.repository or not app.enabled:
        raise AppError(409, "REPOSITORY_NOT_BOUND", "请先启用 App 并关联 GitHub 仓库")
    data = body.model_dump(mode="json")
    validate_rule(db, data)
    data.update(
        repository_id=app.repository["repository_id"],
        repository_full_name=app.repository["full_name"],
        connector_id=app.repository["connector_id"],
    )
    raw, now = secrets.token_urlsafe(32), utcnow()
    row = RuleRecord(
        app_id=id,
        data=data,
        revision=1,
        token_hash=token_hash(raw),
        token_created_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit(db, request, context, "actions.rule.create", row.id)
    db.commit()
    response.headers["ETag"] = '"1"'
    return {"rule": rule_dto(row, request.app.state.settings), "token": raw}


@router.get(
    "/actions-rules/{id}",
    response_model=ActionsRule,
    operation_id="get_actions_rule",
    dependencies=READ,
)
def get_rule(id: UUID, request: Request, response: Response, db: DB):
    row = must_get(db, RuleRecord, id)
    response.headers["ETag"] = f'"{row.revision}"'
    return rule_dto(row, request.app.state.settings)


@router.patch(
    "/actions-rules/{id}",
    response_model=ActionsRule,
    operation_id="update_actions_rule",
    dependencies=WRITE,
)
def update_rule(
    id: UUID,
    body: ActionsRuleUpdate,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    patch = body.model_dump(mode="json", exclude_unset=True)
    if not patch or any(value is None for value in patch.values()):
        raise AppError(422, "VALIDATION_ERROR", "更新字段不能为空")
    row = rule_locked(db, id, if_match)
    data = {**row.data, **patch}
    validate_rule(db, data)
    row.data = data
    mutate_rule(row)
    audit(db, request, context, "actions.rule.update", id)
    db.commit()
    response.headers["ETag"] = f'"{row.revision}"'
    return rule_dto(row, request.app.state.settings)


@router.delete(
    "/actions-rules/{id}", status_code=204, operation_id="delete_actions_rule", dependencies=WRITE
)
def delete_rule(
    id: UUID,
    request: Request,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    row = rule_locked(db, id, if_match)
    row.data = {**row.data, "enabled": False}
    row.token_hash = None
    mutate_rule(row)
    audit(db, request, context, "actions.rule.disable", id)
    db.commit()


@router.post(
    "/actions-rules/{id}/token/rotate",
    response_model=ActionsToken,
    operation_id="rotate_actions_token",
    dependencies=WRITE,
)
def rotate_token(
    id: UUID,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    recent_admin(context)
    row = rule_locked(db, id, if_match)
    raw = secrets.token_urlsafe(32)
    row.token_hash, row.token_created_at = token_hash(raw), utcnow()
    mutate_rule(row)
    audit(db, request, context, "actions.token.rotate", id)
    db.commit()
    response.headers["ETag"] = f'"{row.revision}"'
    return {"token": raw, "created_at": row.token_created_at}


@router.post(
    "/actions-rules/{id}/token/revoke",
    status_code=204,
    operation_id="revoke_actions_token",
    dependencies=WRITE,
)
def revoke_token(
    id: UUID,
    request: Request,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    row = rule_locked(db, id, if_match)
    row.token_hash = None
    mutate_rule(row)
    audit(db, request, context, "actions.token.revoke", id)
    db.commit()


@router.post(
    "/integrations/github-actions/{id}/events",
    response_model=BuildEventAccepted,
    status_code=202,
    operation_id="receive_actions_event",
)
def receive_event(
    id: UUID,
    body: BuildEventRequest,
    request: Request,
    db: DB,
    authorization: Annotated[str | None, Header()] = None,
):
    # Serialize revocation/rotation with acceptance, and never use browser admin authority here.
    lock(db, f"rule:{id}")
    rule = db.get(RuleRecord, id)
    raw = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if (
        not raw
        or len(raw) > 200
        or rule is None
        or not rule.token_hash
        or not secrets.compare_digest(token_hash(raw), rule.token_hash)
    ):
        raise AppError(401, "INVALID_CI_TOKEN", "构建回调凭据无效")
    app = must_get(db, AppRecord, rule.app_id)
    if not rule.data["enabled"] or not app.enabled or not app.repository:
        raise AppError(403, "RULE_DISABLED", "规则或 App 当前不可用")
    if app.repository["repository_id"] != rule.data["repository_id"]:
        raise AppError(409, "SOURCE_CHANGED", "规则对应仓库已变化")
    data = body.model_dump(mode="json")
    if data["repository_id"] != rule.data["repository_id"]:
        raise AppError(403, "REPOSITORY_MISMATCH", "回调仓库与规则不匹配")
    data["asset_ids"] = sorted(set(data["asset_ids"]))
    identity = digest({"rule": str(id), **{k: v for k, v in data.items() if k != "head_sha"}})
    lock(db, "event_identity:" + identity)
    row = db.scalar(select(EventRecord).where(EventRecord.identity == identity))
    duplicate = row is not None
    if row and row.data != data:
        raise AppError(409, "IDEMPOTENCY_CONFLICT", "同一构建事件的提交内容不一致")
    if row is None:
        now = utcnow()
        row = EventRecord(
            app_id=app.id,
            rule_id=id,
            identity=identity,
            data=data,
            rule_snapshot=dict(rule.data),
            state="received",
            stages=stages_initial(),
            assets=[
                {
                    "asset_id": asset,
                    "file_name": None,
                    "entry_id": None,
                    "state": "pending",
                    "error_code": None,
                }
                for asset in data["asset_ids"]
            ],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        enqueue(
            db,
            "build_event",
            resource_id=str(row.id),
            app_id=app.id,
            dedupe_key=f"build_event:{row.id}",
        )
        audit(db, request, None, "actions.event.receive", row.id, kind="ci")
    db.commit()
    return {
        "event_id": row.id,
        "duplicate": duplicate,
        "state": row.state,
        "status_url": f"/api/v1/build-events/{row.id}",
    }


@router.get(
    "/apps/{id}/build-events",
    response_model=BuildEventPage,
    operation_id="list_build_events",
    dependencies=READ,
)
def list_events(
    id: UUID,
    db: DB,
    page_number: int = Query(1, alias="page", ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    state: str | None = None,
):
    must_get(db, AppRecord, id)
    stmt = select(EventRecord).where(EventRecord.app_id == id)
    if state:
        stmt = stmt.where(EventRecord.state == state)
    rows = db.scalars(stmt.order_by(EventRecord.created_at.desc(), EventRecord.id)).all()
    return page(
        [
            event_dto(db, row)
            for row in rows
            if not q or q in row.data["run_id"] or q in row.data["head_sha"]
        ],
        page_number,
        page_size,
    )


@router.get(
    "/build-events/{id}",
    response_model=BuildEvent,
    operation_id="get_build_event",
    dependencies=READ,
)
def get_event(id: UUID, db: DB):
    return event_dto(db, must_get(db, EventRecord, id))


@router.post(
    "/build-events/{id}/retry",
    response_model=TaskAccepted,
    status_code=202,
    operation_id="retry_build_event",
    dependencies=WRITE,
)
def retry_event(
    id: UUID,
    body: BuildRetryRequest,
    request: Request,
    db: DB,
    context: Admin,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    lock(db, f"event:{id}")
    event = must_get(db, EventRecord, id)
    active_rule(db, event)
    key, previous = idem_begin(db, f"event_retry:{id}", idempotency_key, body.model_dump())
    if previous:
        return previous.data
    if body.stage not in event_dto(db, event).retryable_stages:
        raise AppError(409, "STAGE_NOT_RETRYABLE", "该阶段不能重试；未知投递需单独确认可能重复")
    if body.stage == "cache":
        from app.domains.distribution.packages import ensure_cache

        results = [dict(item) for item in event.assets]
        for result in results:
            if result["state"] == "failed":
                result.update(state="pending", error_code=None)
                if result["entry_id"]:
                    entry = must_get(db, DebugRecord, UUID(result["entry_id"]))
                    ensure_cache(db, entry)
        event.assets = results
    elif body.stage == "notify":
        for delivery in db.scalars(select(DeliveryRecord).where(DeliveryRecord.event_id == id)):
            if delivery.state == "failed":
                delivery.state, delivery.error_code, delivery.error_message = "queued", None, None
                enqueue(
                    db,
                    "notification",
                    resource_id=str(delivery.id),
                    app_id=event.app_id,
                    dedupe_key=f"notification:{delivery.id}",
                )
    event.state, event.updated_at = "received", utcnow()
    task = enqueue(
        db, "build_event", resource_id=str(id), app_id=event.app_id, dedupe_key=f"build_event:{id}"
    )
    result = task_accepted(task)
    idem_save(db, key, body.model_dump(), result)
    audit(db, request, context, "actions.event.retry", id)
    db.commit()
    return result
