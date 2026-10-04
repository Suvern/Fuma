from urllib.parse import unquote, urlsplit

from sqlalchemy import select, text

from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.auth.service import utcnow
from app.domains.distribution.models import ChatRecord, DeliveryRecord, EventRecord, RuleRecord
from app.domains.distribution.service import RetryLater, digest, enqueue, lock, state
from app.domains.github.crypto import SecretBox
from app.integrations.feishu import FeishuClient


def safe_return(value, default="/"):
    if value is None:
        return default
    decoded = value
    for _ in range(4):
        decoded = unquote(decoded)
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(c) < 32 for c in decoded)
        or urlsplit(decoded).netloc
    ):
        raise AppError(422, "INVALID_RETURN_PATH", "返回地址必须是站内路径")
    return value


def callback_url(settings):
    return settings.site_url + "/api/v1/auth/feishu/callback"


def feishu_config(db, settings):
    row = state(db, "feishu")
    d = row.data
    return {
        "app_id": d.get("app_id"),
        "has_secret": bool(d.get("secret")),
        "tenant_key": d.get("tenant_key"),
        "enabled": d.get("enabled", False),
        "verified": d.get("verified", False),
        "callback_url": callback_url(settings),
        "last_tested_at": d.get("last_tested_at"),
        "checks": d.get("checks", []),
        "revision": row.revision,
    }


def client(db, settings, *, active=False):
    row = state(db, "feishu")
    d = row.data
    if not d.get("app_id") or not d.get("secret"):
        raise AppError(409, "FEISHU_NOT_CONFIGURED", "请先配置飞书应用")
    if active and not (d.get("enabled") and d.get("verified") and d.get("tenant_key")):
        raise AppError(403, "FEISHU_NOT_ACTIVE", "飞书应用尚未完成可信租户绑定或已停用")
    return FeishuClient(d["app_id"], SecretBox(settings).decrypt(d["secret"], scope="feishu"))


def verify_download_context(db, context):
    row = state(db, "feishu")
    d = row.data
    if (
        not d.get("enabled")
        or not d.get("verified")
        or d.get("tenant_key") != context.user.tenant_key
        or context.user.provider_app_id != d.get("app_id")
        or not context.user.active
        or row.revision != context.session.feishu_config_revision
    ):
        raise AppError(403, "ELIGIBILITY_UNVERIFIED", "飞书配置或资格已变更，请重新登录")


def bot_config(db):
    row, fs = state(db, "bot"), state(db, "feishu")
    d = row.data
    return {
        "app_id": fs.data.get("app_id"),
        "tenant_key": fs.data.get("tenant_key"),
        "bot_name": d.get("bot_name"),
        "bot_open_id": d.get("bot_open_id"),
        "enabled": d.get("enabled", False),
        "verified": d.get("verified", False),
        "checks": d.get("checks", []),
        "last_tested_at": d.get("last_tested_at"),
        "revision": row.revision,
    }


def bot_client(db, settings):
    bot = state(db, "bot")
    if not bot.data.get("enabled") or not bot.data.get("verified"):
        raise AppError(409, "BOT_NOT_READY", "机器人尚未启用或验证")
    return client(db, settings, active=True)


def sync_chats(db, settings):
    fsrev = state(db, "feishu").revision
    botrev = state(db, "bot").revision
    api = bot_client(db, settings)
    try:
        chats = api.chats()
    finally:
        api.close()
    # Take the lock only after the complete provider snapshot has arrived.
    fs = state(db, "feishu", locked=True)
    bot = state(db, "bot", locked=True)
    if fs.revision != fsrev or bot.revision != botrev:
        raise AppError(409, "CONFIG_CHANGED", "飞书配置已变更，请重新同步")
    now = utcnow()
    incoming = {c["chat_id"]: c for c in chats if c.get("chat_id")}
    for row in db.scalars(select(ChatRecord)):
        if row.chat_id not in incoming:
            row.membership, row.send_status, row.synced_at = "removed", "unavailable", now
    for chat_id, item in incoming.items():
        row = db.get(ChatRecord, chat_id)
        if row is None:
            row = ChatRecord(chat_id=chat_id)
            db.add(row)
        row.name = item.get("name", "未命名群")[:500]
        avatar = item.get("avatar")
        row.avatar_url = avatar if avatar and avatar.startswith("https://") else None
        row.membership, row.synced_at = "joined", now
        if not row.send_status or row.send_status == "unavailable":
            row.send_status = "unverified"
    sync = state(db, "chats", locked=True)
    sync.data = {"synced_at": now.isoformat(), "sync_state": "ready", "sync_error_code": None}
    db.commit()


def validate_chats(db, chat_ids):
    ids = list(dict.fromkeys(str(c) for c in chat_ids))
    for chat_id in ids:
        row = db.get(ChatRecord, chat_id)
        if row is None or row.membership != "joined":
            raise AppError(422, "CHAT_NOT_JOINED", "只能选择机器人已加入的群，请刷新群列表")
    return ids


def create_delivery(
    db, chat_id, card, *, event_id=None, app_id=None, kind="test", enqueue_task=True
):
    chat = db.get(ChatRecord, chat_id)
    now = utcnow()
    delivery = DeliveryRecord(
        event_id=event_id,
        app_id=app_id,
        chat_id=chat_id,
        chat_name=chat.name if chat else "已移除群",
        kind=kind,
        state="queued",
        attempts=0,
        card=card,
        created_at=now,
        updated_at=now,
    )
    db.add(delivery)
    db.flush()
    if enqueue_task:
        enqueue(
            db,
            "notification",
            resource_id=str(delivery.id),
            app_id=app_id,
            dedupe_key=f"notification:{delivery.id}",
        )
    return delivery


def delivery_dto(row):
    names = (
        "id",
        "event_id",
        "app_id",
        "chat_id",
        "chat_name",
        "kind",
        "state",
        "attempts",
        "provider_message_id",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
        "card",
    )
    return {**{n: getattr(row, n) for n in names}, "can_retry": row.state in {"failed", "unknown"}}


def send_delivery(db, settings, delivery_id):
    # Different task IDs may point to one delivery. Keep this lock across all commits/I/O.
    key = int(digest(f"delivery_execution:{delivery_id}")[:15], 16)
    with db.get_bind().connect() as fence:
        owned = fence.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        fence.commit()
        if not owned:
            raise RetryLater(5)
        try:
            _send_delivery(db, settings, delivery_id)
        finally:
            fence.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            fence.commit()


def _send_delivery(db, settings, delivery_id):
    from app.domains.access.task_authorization import check_task_authorization

    candidate = db.get(DeliveryRecord, delivery_id)
    if candidate is None:
        return
    app_id = candidate.app_id

    def lock_delivery():
        # The same order applies to browser retries and CI deliveries.
        check_task_authorization(db)
        state(db, "feishu", locked=True)
        if app_id:
            db.scalar(select(AppRecord).where(AppRecord.id == app_id).with_for_update())
        lock(db, f"delivery:{delivery_id}")
        return db.get(DeliveryRecord, delivery_id, populate_existing=True)

    row = lock_delivery()
    if row is None or row.state in {"succeeded", "unknown", "failed"}:
        return
    if row.state == "sending":
        # Owning the mutex proves no other live sender owns this delivery.
        row.state, row.error_code = "unknown", "EXTERNAL_RESULT_UNKNOWN"
        row.error_message = "上次发送中断，结果未知，请人工核对后确认是否重发"
        row.updated_at = utcnow()
        db.commit()
        return
    fs_revision, bot_revision = state(db, "feishu").revision, state(db, "bot").revision
    api = None
    try:
        api = bot_client(db, settings)
        db.commit()  # Never hold role/configuration locks during provider token I/O.
        api.tenant_token()
        row = lock_delivery()
        cfg = state(db, "feishu", locked=True)
        bot = state(db, "bot", locked=True)
        if cfg.revision != fs_revision or bot.revision != bot_revision:
            raise AppError(409, "CONFIG_CHANGED", "通知准备期间机器人配置已变化")
        validate_chats(db, [row.chat_id])
        if row.event_id:
            event = db.get(EventRecord, row.event_id)
            app = db.scalar(select(AppRecord).where(AppRecord.id == row.app_id).with_for_update())
            rule = (
                db.scalar(
                    select(RuleRecord).where(RuleRecord.id == event.rule_id).with_for_update()
                )
                if event
                else None
            )
            if (
                not app
                or not app.enabled
                or not rule
                or not rule.data.get("enabled")
                or not rule.token_hash
            ):
                raise AppError(409, "RULE_DISABLED", "App 或 Actions 规则已停用，不再发送通知")
            if row.chat_id not in rule.data.get("chat_ids", []):
                raise AppError(409, "TARGET_CHANGED", "通知目标已从规则中移除")
    except AppError as exc:
        if api:
            api.close()
        row.state, row.error_code, row.error_message = "failed", exc.code, exc.message
        row.updated_at = utcnow()
        db.commit()
        if exc.code == "TASK_AUTHORIZATION_REVOKED":
            raise
        return
    # Committing sending before outbound I/O makes crash recovery conservatively unknown.
    row.state, row.updated_at = "sending", utcnow()
    row.attempts += 1
    db.commit()
    authorization_error = None
    try:
        check_task_authorization(db)
        db.commit()  # Sending is durable; later revocation cannot retract submitted I/O.
        message_id = api.send_card(row.chat_id, row.card, row.id)
    except AppError as exc:
        row.state = (
            "unknown"
            if exc.code
            in {"PROVIDER_UNAVAILABLE", "EXTERNAL_RESULT_UNKNOWN", "PROVIDER_INVALID_RESPONSE"}
            else "failed"
        )
        row.error_code, row.error_message = exc.code, exc.message
        if exc.code == "TASK_AUTHORIZATION_REVOKED":
            authorization_error = exc
        if row.state == "failed" and exc.code != "TASK_AUTHORIZATION_REVOKED":
            chat = db.get(ChatRecord, row.chat_id)
            if chat:
                chat.send_status = "unavailable"
    except Exception:
        row.state, row.error_code = "unknown", "EXTERNAL_RESULT_UNKNOWN"
        row.error_message = "发送结果未知，请人工核对后确认是否重发"
    else:
        row.state, row.provider_message_id = "succeeded", message_id
        row.error_code, row.error_message = None, None
        chat = db.get(ChatRecord, row.chat_id)
        if chat:
            chat.send_status = "available"
    finally:
        api.close()
    row.updated_at = utcnow()
    db.commit()
    if authorization_error:
        raise authorization_error
