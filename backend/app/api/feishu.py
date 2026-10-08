import secrets
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api import contracts as dto
from app.api.app_access import ScopedManager
from app.api.dependencies import CSRF, DB, Admin, optional_context, require_revision
from app.core.errors import AppError
from app.domains.access.authorization import manageable_app_ids
from app.domains.applications.models import AppRecord
from app.domains.audit.service import record_audit
from app.domains.auth.models import AuthSession, User
from app.domains.auth.service import AuthContext, create_user_session, token_hash, utcnow
from app.domains.distribution import feishu as fs
from app.domains.distribution.models import (
    AppNotificationTemplate,
    BindingProofRecord,
    ChatRecord,
    DeliveryRecord,
    EventRecord,
    OAuthState,
    RuleRecord,
)
from app.domains.distribution.service import (
    enqueue,
    idem_begin,
    idem_save,
    lock,
    must_get,
    page,
    state,
    task_accepted,
)
from app.domains.github.crypto import SecretBox
from app.integrations.feishu import FeishuClient

router = APIRouter(tags=["Feishu"])


@router.get(
    "/apps/{id}/release-notification-template",
    response_model=dto.ReleaseNotificationTemplateConfig,
    operation_id="get_release_notification_template",
)
def get_release_notification_template(
    id: UUID, request: Request, response: Response, db: DB, manager: ScopedManager
):
    from app.domains.distribution.notification_templates import template_config

    value = template_config(db, must_get(db, AppRecord, id), request.app.state.settings.site_url)
    response.headers["ETag"] = f'"{value["revision"]}"'
    return value


@router.put(
    "/apps/{id}/release-notification-template",
    response_model=dto.ReleaseNotificationTemplateConfig,
    operation_id="update_release_notification_template",
)
def update_release_notification_template(
    id: UUID,
    body: dto.ReleaseNotificationTemplate,
    request: Request,
    response: Response,
    db: DB,
    manager: ScopedManager,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    from app.domains.distribution.notification_templates import validate_template

    app = must_get(db, AppRecord, id)
    if app.archived_at:
        raise AppError(409, "APP_ARCHIVED", "归档应用不能修改通知模板")
    data = body.model_dump()
    validate_template(data)
    # ScopedManager holds the App lock, serializing first-save and later edits alike.
    row = db.get(AppNotificationTemplate, id)
    require_revision(if_match, row.revision if row else 0)
    if row is None:
        row = AppNotificationTemplate(app_id=id, revision=0)
        db.add(row)
    row.data = data
    row.revision += 1
    record_audit(
        db,
        action="notification_template.update",
        resource_type="notification_template",
        resource_id=str(id),
        app_id=id,
        request_id=request.state.request_id,
        actor_id=str(manager.user.id),
        summary="更新 Release 安装包就绪通知模板，仅用于新生成的通知",
    )
    db.commit()
    return get_release_notification_template(id, request, response, db, manager)


def check(code, status, message):
    return {"code": code, "status": status, "message": message}


@router.get("/settings/feishu", response_model=dto.FeishuConfig, operation_id="get_feishu_config")
def config(request: Request, response: Response, db: DB, admin: Admin):
    value = fs.feishu_config(db, request.app.state.settings)
    response.headers["ETag"] = f'"{value["revision"]}"'
    return value


@router.put(
    "/settings/feishu", response_model=dto.FeishuConfig, operation_id="update_feishu_config"
)
def update_config(
    body: dto.FeishuConfigUpdate,
    request: Request,
    response: Response,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    fields = body.model_dump(exclude_unset=True)
    if any(value is None for value in fields.values()) or not body.app_id.strip():
        raise AppError(422, "VALIDATION_ERROR", "飞书配置字段不能显式设置为空")
    current = state(db, "feishu")
    require_revision(if_match, current.revision)
    changed = current.data.get("app_id") != body.app_id or body.app_secret is not None
    if changed and not body.app_secret:
        raise AppError(422, "SECRET_REQUIRED", "更换应用时需要同时填写应用密钥")
    if changed:
        # Test without changing active state. Bad credentials must not lock out an existing tenant.
        candidate = FeishuClient(body.app_id, body.app_secret)
        try:
            candidate.tenant_token()
        finally:
            candidate.close()
    row = state(db, "feishu", locked=True)
    require_revision(if_match, row.revision)
    prior = row.data
    secret = (
        SecretBox(request.app.state.settings).encrypt(body.app_secret, scope="feishu")
        if body.app_secret
        else prior.get("secret")
    )
    verified = prior.get("verified", False) and not changed
    if verified and body.tenant_key and body.tenant_key != prior.get("tenant_key"):
        raise AppError(409, "TENANT_MISMATCH", "当前部署已绑定其他租户")
    row.data = {
        "app_id": body.app_id,
        "secret": secret,
        "enabled": body.enabled,
        "expected_tenant": body.tenant_key,
        "tenant_key": prior.get("tenant_key") if verified else None,
        "verified": verified,
        "checks": [],
        "last_tested_at": None,
    }
    row.revision += 1
    bot = state(db, "bot", locked=True)
    bot.data = {**bot.data, "verified": False, "checks": []}
    bot.revision += 1
    for session in db.scalars(
        select(AuthSession).where(AuthSession.kind == "feishu", AuthSession.revoked_at.is_(None))
    ):
        session.revoked_at = utcnow()
    if changed:
        for chat in db.scalars(select(ChatRecord)):
            chat.membership, chat.send_status = "unknown", "unavailable"
        state(db, "chats", locked=True).data = {}
        for rule in db.scalars(select(RuleRecord)):
            rule.data = {**rule.data, "enabled": False}
            rule.revision += 1
            rule.updated_at = utcnow()
    record_audit(
        db,
        action="feishu.configure",
        resource_type="feishu",
        request_id=request.state.request_id,
        actor_id=str(admin.user.id),
    )
    db.commit()
    return config(request, response, db, admin)


@router.post(
    "/settings/feishu/test",
    response_model=dto.ConnectionTestResult,
    operation_id="test_feishu_config",
)
def test_config(request: Request, db: DB, admin: Admin, csrf: CSRF):
    revision = state(db, "feishu").revision
    api = fs.client(db, request.app.state.settings)
    try:
        api.tenant_token()
        checks = [
            check("tenant_token", "pass", "应用凭据可用"),
            check("sso", "unknown", "通过租户绑定登录验证 SSO"),
        ]
        status = "partial"
    except AppError:
        checks, status = (
            [check("tenant_token", "fail", "应用凭据验证失败，请检查配置和权限")],
            "failed",
        )
    finally:
        api.close()
    now = utcnow()
    row = state(db, "feishu", locked=True)
    if row.revision != revision:
        raise AppError(409, "CONFIG_CHANGED", "检测期间配置发生变化，请重新检测")
    row.data = {**row.data, "checks": checks, "last_tested_at": now.isoformat()}
    db.commit()
    return {"status": status, "checks": checks, "tested_at": now}


def begin_oauth(db, settings, session, purpose, return_to):
    row = state(db, "feishu", locked=True)
    api = fs.client(db, settings, active=purpose == "login")
    api.close()
    raw, expires = secrets.token_urlsafe(32), utcnow() + timedelta(minutes=10)
    db.add(
        OAuthState(
            state_hash=token_hash(raw),
            session_id=session.id,
            config_revision=row.revision,
            purpose=purpose,
            return_to=return_to,
            expires_at=expires,
            consumed=False,
        )
    )
    url = "https://accounts.feishu.cn/open-apis/authen/v1/authorize?" + urlencode(
        {
            "app_id": row.data["app_id"],
            "redirect_uri": fs.callback_url(settings),
            "state": raw,
            "response_type": "code",
        }
    )
    db.commit()
    return url, expires


@router.post(
    "/settings/feishu/binding/start",
    response_model=dto.FeishuBindingStarted,
    operation_id="start_feishu_binding",
)
def binding_start(body: dto.FeishuBindingStart, request: Request, db: DB, admin: Admin, csrf: CSRF):
    if not admin.session.authenticated_at or admin.session.authenticated_at < utcnow() - timedelta(
        minutes=15
    ):
        raise AppError(403, "RECENT_AUTH_REQUIRED", "请重新登录管理员后绑定租户")
    url, expires = begin_oauth(
        db,
        request.app.state.settings,
        admin.session,
        "bind",
        fs.safe_return(body.return_to, "/admin/settings/feishu"),
    )
    return {"authorization_url": url, "expires_at": expires}


@router.get(
    "/auth/feishu/start",
    operation_id="start_feishu_sso",
    response_class=RedirectResponse,
    status_code=302,
)
def login_start(
    request: Request,
    db: DB,
    context: Annotated[AuthContext | None, Depends(optional_context)],
    return_to: Annotated[str | None, Query(max_length=2048)] = None,
):
    destination = fs.safe_return(return_to)
    response = RedirectResponse("/", status_code=302)
    if context is None:
        session, _ = create_user_session(db, response, None, request.app.state.settings)
    else:
        session = context.session
    url, _ = begin_oauth(db, request.app.state.settings, session, "login", destination)
    response.headers["Location"] = url
    return response


@router.get(
    "/auth/feishu/callback",
    operation_id="finish_feishu_sso",
    response_class=RedirectResponse,
    status_code=303,
)
def callback(
    request: Request,
    db: DB,
    context: Annotated[AuthContext | None, Depends(optional_context)],
    code: Annotated[str | None, Query(max_length=4096)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
):
    def failed(reason, return_to=None):
        params = {"error": reason}
        if return_to:
            params["return_to"] = fs.safe_return(return_to)
        return RedirectResponse("/login?" + urlencode(params), status_code=303)

    if not context or not state:
        return failed("OAUTH_STATE_INVALID")
    lock(db, f"oauth:{token_hash(state)}")
    oauth = db.get(OAuthState, token_hash(state))
    if (
        not oauth
        or oauth.consumed
        or oauth.expires_at <= utcnow()
        or oauth.session_id != context.session.id
    ):
        return failed("OAUTH_STATE_INVALID")
    oauth.consumed = True
    db.commit()
    if error or not code:
        return failed("OAUTH_CANCELLED", oauth.return_to)
    settings = request.app.state.settings
    try:
        api = fs.client(db, settings, active=oauth.purpose == "login")
        try:
            user_info = api.oauth_user(code, fs.callback_url(settings))
        finally:
            api.close()
        from app.domains.distribution.service import state as get_state

        cfg = get_state(db, "feishu", locked=True)
        if cfg.revision != oauth.config_revision:
            raise AppError(409, "CONFIG_CHANGED", "配置已变更")
        # Recheck the originating session after network I/O (logout/revocation races).
        db.refresh(context.session)
        if context.session.revoked_at or context.session.expires_at <= utcnow():
            raise AppError(401, "AUTHENTICATION_REQUIRED", "会话已结束")
        tenant = user_info["tenant_key"]
        response = RedirectResponse(oauth.return_to, status_code=303)
        if oauth.purpose == "bind":
            if not context.user or context.user.kind != "local":
                raise AppError(403, "ADMIN_REQUIRED", "绑定需要管理员")
            expected = cfg.data.get("expected_tenant")
            if expected and expected != tenant:
                raise AppError(403, "TENANT_MISMATCH", "租户不匹配")
            db.add(
                BindingProofRecord(
                    session_id=context.session.id,
                    config_revision=cfg.revision,
                    app_id=cfg.data["app_id"],
                    tenant_key=tenant,
                    display_name=user_info.get("name", "飞书用户")[:100],
                    expires_at=utcnow() + timedelta(minutes=10),
                    consumed=False,
                )
            )
        else:
            if tenant != cfg.data.get("tenant_key"):
                raise AppError(403, "TENANT_MISMATCH", "租户不匹配")
            provider_app_id = cfg.data["app_id"]
            lock(db, f"user:{provider_app_id}:{tenant}:{user_info['open_id']}")
            user = db.scalar(
                select(User)
                .where(
                    User.provider_app_id == provider_app_id,
                    User.tenant_key == tenant,
                    User.open_id == user_info["open_id"],
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if user is None:
                user = User(
                    kind="feishu",
                    tenant_key=tenant,
                    provider_app_id=provider_app_id,
                    open_id=user_info["open_id"],
                    display_name=user_info.get("name", "飞书用户")[:100],
                )
                db.add(user)
                db.flush()
            if not user.active:
                raise AppError(403, "ACCOUNT_DISABLED", "此账号已停用，请联系管理员")
            user.identity_verified_at = utcnow()
            create_user_session(
                db,
                response,
                user,
                settings,
                old_session=context.session,
                eligibility_until=utcnow() + timedelta(seconds=300),
                config_revision=cfg.revision,
            )
        db.commit()
        return response
    except AppError as exc:
        db.rollback()
        return failed(exc.code, oauth.return_to)


@router.get(
    "/settings/feishu/binding/proof",
    response_model=dto.FeishuBindingProof,
    operation_id="get_feishu_binding_proof",
)
def binding_proof(db: DB, admin: Admin):
    row = db.scalar(
        select(BindingProofRecord)
        .where(
            BindingProofRecord.session_id == admin.session.id,
            BindingProofRecord.expires_at > utcnow(),
        )
        .order_by(BindingProofRecord.expires_at.desc())
    )
    if row is None:
        raise AppError(404, "BINDING_PROOF_NOT_FOUND", "请先完成飞书绑定登录")
    return {
        "binding_id": row.id,
        "app_id": row.app_id,
        "tenant_key": row.tenant_key,
        "display_name": row.display_name,
        "expires_at": row.expires_at,
        "consumed": row.consumed,
    }


@router.post(
    "/settings/feishu/binding/confirm",
    response_model=dto.FeishuConfig,
    operation_id="confirm_feishu_binding",
)
def binding_confirm(
    body: dto.FeishuBindingConfirm,
    request: Request,
    response: Response,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    if not admin.session.authenticated_at or admin.session.authenticated_at < utcnow() - timedelta(
        minutes=15
    ):
        raise AppError(403, "RECENT_AUTH_REQUIRED", "请重新登录管理员后绑定租户")
    cfg = state(db, "feishu", locked=True)
    require_revision(if_match, cfg.revision)
    proof = must_get(db, BindingProofRecord, body.binding_id)
    if (
        proof.session_id != admin.session.id
        or proof.consumed
        or proof.expires_at <= utcnow()
        or proof.config_revision != cfg.revision
        or proof.app_id != cfg.data.get("app_id")
    ):
        raise AppError(403, "BINDING_PROOF_INVALID", "租户绑定凭据无效，请重新验证")
    proof.consumed = True
    cfg.data = {**cfg.data, "tenant_key": proof.tenant_key, "verified": True}
    cfg.revision += 1
    bot = state(db, "bot", locked=True)
    bot.data = {**bot.data, "verified": False, "checks": []}
    bot.revision += 1
    for session in db.scalars(
        select(AuthSession).where(AuthSession.kind == "feishu", AuthSession.revoked_at.is_(None))
    ):
        session.revoked_at = utcnow()
    for chat in db.scalars(select(ChatRecord)):
        chat.membership, chat.send_status = "unknown", "unavailable"
    state(db, "chats", locked=True).data = {}
    for rule in db.scalars(select(RuleRecord)):
        rule.data = {**rule.data, "enabled": False}
        rule.revision += 1
        rule.updated_at = utcnow()
    record_audit(
        db,
        action="feishu.bind",
        resource_type="feishu",
        request_id=request.state.request_id,
        actor_id=str(admin.user.id),
    )
    db.commit()
    return config(request, response, db, admin)


@router.get("/settings/feishu-bot", response_model=dto.BotConfig, operation_id="get_bot_config")
def get_bot(response: Response, db: DB, admin: Admin):
    value = fs.bot_config(db)
    response.headers["ETag"] = f'"{value["revision"]}"'
    return value


@router.put("/settings/feishu-bot", response_model=dto.BotConfig, operation_id="update_bot_config")
def update_bot(
    body: dto.BotUpdate,
    request: Request,
    response: Response,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    row = state(db, "bot", locked=True)
    require_revision(if_match, row.revision)
    row.data = {**row.data, "enabled": body.enabled}
    row.revision += 1
    record_audit(
        db,
        action="bot.configure",
        resource_type="bot",
        request_id=request.state.request_id,
        actor_id=str(admin.user.id),
    )
    db.commit()
    return get_bot(response, db, admin)


@router.post(
    "/settings/feishu-bot/test",
    response_model=dto.ConnectionTestResult,
    operation_id="test_bot_capabilities",
)
def test_bot(request: Request, db: DB, admin: Admin, csrf: CSRF):
    fs_revision = state(db, "feishu").revision
    bot_revision = state(db, "bot").revision
    api = fs.client(db, request.app.state.settings, active=True)
    info, checks = {}, []
    try:
        info = api.bot_info()
        checks.append(check("identity", "pass", "机器人身份已确认"))
        api.chats()
        checks.append(check("chats", "pass", "已验证完整群列表读取"))
        checks.append(check("send", "unknown", "请选择群发送测试卡片验证投递"))
        status = "partial"
    except AppError:
        checks.append(check("capabilities", "fail", "机器人身份或群读取失败，请检查权限"))
        status = "failed"
    finally:
        api.close()
    now = utcnow()
    cfg = state(db, "feishu", locked=True)
    row = state(db, "bot", locked=True)
    if cfg.revision != fs_revision or row.revision != bot_revision:
        raise AppError(409, "CONFIG_CHANGED", "检测期间应用或机器人配置已变化，请重新检测")
    row.data = {
        **row.data,
        "verified": status != "failed",
        "bot_name": info.get("app_name"),
        "bot_open_id": info.get("open_id"),
        "checks": checks,
        "last_tested_at": now.isoformat(),
    }
    db.commit()
    return {"status": status, "checks": checks, "tested_at": now}


@router.get(
    "/settings/feishu-bot/chats", response_model=dto.ChatPage, operation_id="list_bot_chats"
)
def chats(
    db: DB,
    admin: Admin,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: str | None = None,
):
    rows = db.scalars(select(ChatRecord).order_by(ChatRecord.name)).all()
    items = [
        {
            n: getattr(r, n)
            for n in ("chat_id", "name", "avatar_url", "membership", "send_status", "synced_at")
        }
        for r in rows
        if not q or q.casefold() in r.name.casefold()
    ]
    sync = state(db, "chats").data
    return page(
        items,
        page_number,
        page_size,
        synced_at=sync.get("synced_at"),
        sync_state=sync.get("sync_state", "never"),
        sync_error_code=sync.get("sync_error_code"),
    )


@router.post(
    "/settings/feishu-bot/chats/refresh",
    response_model=dto.TaskAccepted,
    status_code=202,
    operation_id="refresh_bot_chats",
)
def refresh_chats(
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    api = fs.bot_client(db, request.app.state.settings)
    api.close()
    key, previous = idem_begin(db, "chat_sync", idempotency_key, {})
    if previous:
        return previous.data
    task = enqueue(db, "chat_sync", dedupe_key="chat_sync")
    row = state(db, "chats", locked=True)
    row.data = {**row.data, "sync_state": "syncing", "sync_error_code": None}
    result = task_accepted(task)
    idem_save(db, key, {}, result)
    db.commit()
    return result


@router.post(
    "/settings/feishu-bot/test-message",
    response_model=dto.TaskAccepted,
    status_code=202,
    operation_id="send_bot_test_message",
)
def test_message(
    body: dto.BotTestRequest,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    api = fs.bot_client(db, request.app.state.settings)
    api.close()
    payload = body.model_dump(mode="json")
    ids = fs.validate_chats(db, payload["chat_ids"])
    key, previous = idem_begin(db, "test_message", idempotency_key, payload)
    if previous:
        return previous.data
    card = {
        "title": "Fuma 连接测试",
        "summary": "机器人测试通知，请在 Fuma 查看投递记录。",
        "app_name": None,
        "mode": "debug",
        "version_label": None,
        "file_names": [],
        "result": "test",
        "occurred_at": utcnow().isoformat(),
        "page_url": None,
    }
    deliveries = [fs.create_delivery(db, chat_id, card, enqueue_task=False) for chat_id in ids]
    task = enqueue(db, "notification", payload={"delivery_ids": [str(d.id) for d in deliveries]})
    result = task_accepted(task)
    idem_save(db, key, payload, result)
    db.commit()
    return result


@router.get("/notifications", response_model=dto.DeliveryPage, operation_id="list_notifications")
def notifications(
    db: DB,
    admin: ScopedManager,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: str | None = None,
    app_id: UUID | None = None,
    state_filter: Annotated[str | None, Query(alias="state")] = None,
):
    stmt = select(DeliveryRecord).order_by(DeliveryRecord.created_at.desc())
    ids = manageable_app_ids(db, admin)
    if ids is not None:
        stmt = stmt.where(DeliveryRecord.app_id.in_(ids))
    rows = db.scalars(stmt).all()
    return page(
        [
            fs.delivery_dto(r)
            for r in rows
            if (not app_id or r.app_id == app_id)
            and (not state_filter or r.state == state_filter)
            and (not q or q.casefold() in r.chat_name.casefold())
        ],
        page_number,
        page_size,
    )


@router.get("/notifications/{id}", response_model=dto.Delivery, operation_id="get_notification")
def notification(id: UUID, db: DB, admin: ScopedManager):
    return fs.delivery_dto(must_get(db, DeliveryRecord, id))


@router.post(
    "/notifications/{id}/retry",
    response_model=dto.TaskAccepted,
    status_code=202,
    operation_id="retry_notification",
)
def retry_notification(
    id: UUID,
    body: dto.DeliveryRetryRequest,
    request: Request,
    db: DB,
    admin: ScopedManager,
    csrf: CSRF,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    lock(db, f"delivery:{id}")
    row = must_get(db, DeliveryRecord, id)
    payload = body.model_dump(mode="json")
    key, previous = idem_begin(db, f"notification_retry:{id}", idempotency_key, payload)
    if previous:
        return previous.data
    if row.state not in {"failed", "unknown"}:
        raise AppError(409, "NOT_RETRYABLE", "此通知当前不可重试")
    if row.state == "unknown" and not body.acknowledge_possible_duplicate:
        raise AppError(409, "DUPLICATE_ACK_REQUIRED", "请确认重试可能造成重复通知")
    fs.validate_chats(db, [row.chat_id])
    row.state, row.error_code, row.error_message = "queued", None, None
    task = enqueue(
        db, "notification", resource_id=str(id), app_id=row.app_id, dedupe_key=f"notification:{id}"
    )
    if row.event_id:
        lock(db, f"event:{row.event_id}")
        event = db.get(EventRecord, row.event_id, populate_existing=True)
        if event:
            event.state, event.updated_at = "notifying", utcnow()
            enqueue(
                db,
                "build_event",
                resource_id=str(event.id),
                app_id=event.app_id,
                dedupe_key=f"build_event:{event.id}",
            )
    record_audit(
        db,
        action="notification.retry",
        resource_type="notification",
        resource_id=str(id),
        request_id=request.state.request_id,
        actor_id=str(admin.user.id),
    )
    result = task_accepted(task)
    idem_save(db, key, payload, result)
    db.commit()
    return result
