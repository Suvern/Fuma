"""Shared backend authority with explicit transaction fences for writes.

Lock order: Feishu configuration advisory lock -> actor User shared row lock ->
App -> domain aggregates. Never call a locking helper after taking an App lock.
"""

from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.auth.models import AppRoleRecord, User
from app.domains.auth.service import AuthContext, utcnow


def is_rescue_admin(user):
    return user.kind == "local" and user.username == "admin"


def identity_verified(db, user, config=None):
    from app.domains.distribution.service import state

    if is_rescue_admin(user):
        return True
    if user.kind != "feishu" or not user.identity_verified_at or not user.provider_app_id:
        return False
    config = config or state(db, "feishu")
    return bool(
        config.data.get("verified")
        and user.provider_app_id == config.data.get("app_id")
        and user.tenant_key == config.data.get("tenant_key")
    )


def effective_role(db, user):
    if not user.active:
        return "downloader"
    if is_rescue_admin(user):
        return "admin"
    return user.global_role if identity_verified(db, user) else "downloader"


def assigned_app_ids(db, user):
    return set(db.scalars(select(AppRoleRecord.app_id).where(AppRoleRecord.user_id == user.id)))


def current_authority(db, context: AuthContext, *, lock=False):
    from app.domains.distribution.service import state

    if not context.user:
        raise AppError(401, "AUTHENTICATION_REQUIRED", "请先登录")
    config = None
    if context.user.kind == "feishu":
        config = state(db, "feishu", locked=lock)
    db.refresh(context.user, with_for_update={"read": True} if lock and config else None)
    db.refresh(context.session)
    user, session = context.user, context.session
    now = utcnow()
    if not user.active or session.revoked_at or session.expires_at <= now:
        raise AppError(401, "AUTHENTICATION_REQUIRED", "账号已停用或会话已结束，请重新登录")
    if user.must_change_password:
        raise AppError(403, "PASSWORD_CHANGE_REQUIRED", "首次登录必须先修改管理员密码")
    if user.kind == "feishu" and (
        not identity_verified(db, user, config)
        or not config.data.get("enabled")
        or session.feishu_config_revision != config.revision
        or not session.eligibility_until
        or session.eligibility_until <= now
        or (session.eligibility_until - now).total_seconds() > 300
    ):
        raise AppError(403, "ELIGIBILITY_UNVERIFIED", "飞书身份或资格已变化，请重新登录验证")
    db.info["actor_user_id"] = user.id
    db.info["actor_permission_revision"] = user.permission_revision
    return effective_role(db, user)


def require_manager(db, context, *, lock=False):
    if current_authority(db, context, lock=lock) not in {"admin", "maintainer"}:
        raise AppError(403, "MANAGER_REQUIRED", "此操作需要后台管理权限")
    return context


def require_global_admin(db, context, *, lock=False):
    if current_authority(db, context, lock=lock) != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "此操作需要全局管理员权限")
    return context


def manageable_app_ids(db, context):
    require_manager(db, context)
    return (
        None if effective_role(db, context.user) == "admin" else assigned_app_ids(db, context.user)
    )


def require_app_permission(db, context, app_id, *, lock=False):
    require_manager(db, context, lock=lock)
    app_id = UUID(str(app_id))
    allowed = (
        None if effective_role(db, context.user) == "admin" else assigned_app_ids(db, context.user)
    )
    # Resolve scope from the stored resource before calling this function. Use a
    # uniform 404 so a guessed foreign App identifier does not disclose existence.
    if allowed is not None and app_id not in allowed:
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "App 不存在或不可访问")
    statement = select(AppRecord).where(AppRecord.id == app_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    app = db.scalar(statement)
    if app is None:
        raise AppError(404, "RESOURCE_NOT_AVAILABLE", "App 不存在或不可访问")
    db.info["actor_app_id"] = app_id
    return app


def require_actor_permission(db, user_id, app_id, *, lock=True):
    """Task actor recheck: authority survives browser expiry, never revocation."""
    from app.domains.distribution.service import state

    user = db.get(User, UUID(str(user_id)))
    if user is None:
        raise AppError(403, "TASK_ACTOR_REVOKED", "任务发起者已不可用")
    config = state(db, "feishu", locked=lock) if user.kind == "feishu" else None
    db.refresh(user, with_for_update={"read": True} if lock and config else None)
    if (
        not user.active
        or user.must_change_password
        or (config and (not config.data.get("enabled") or not identity_verified(db, user, config)))
    ):
        raise AppError(403, "TASK_ACTOR_REVOKED", "任务发起者身份或权限已失效")
    role = effective_role(db, user)
    if role != "admin" and (
        role != "maintainer"
        or app_id is None
        or UUID(str(app_id)) not in assigned_app_ids(db, user)
    ):
        raise AppError(403, "TASK_ACTOR_REVOKED", "任务发起者已无对应管理权限")
    return user
