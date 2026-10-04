import re
import secrets
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.domains.auth.models import AuthSession, User
from app.domains.auth.service import AuthContext, cookie_name, token_hash, utcnow
from app.infrastructure.database import get_session

DB = Annotated[Session, Depends(get_session)]


def optional_context(request: Request, db: DB) -> AuthContext | None:
    raw = request.cookies.get(cookie_name(request.app.state.settings), "")
    if not raw or len(raw) > 200:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(raw)))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        return None
    user = db.get(User, session.user_id) if session.user_id else None
    if session.user_id and (user is None or not user.active):
        return None
    return AuthContext(session=session, user=user)


def require_context(
    context: Annotated[AuthContext | None, Depends(optional_context)],
) -> AuthContext:
    if context is None:
        raise AppError(401, "AUTHENTICATION_REQUIRED", "请先建立浏览器会话")
    return context


def require_user(context: Annotated[AuthContext, Depends(require_context)]) -> AuthContext:
    if context.user is None:
        raise AppError(401, "AUTHENTICATION_REQUIRED", "请先登录")
    return context


def require_local_admin(context: Annotated[AuthContext, Depends(require_user)]) -> AuthContext:
    if context.user.kind != "local" or context.user.username != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "此操作需要管理员权限")
    return context


def require_admin(
    context: Annotated[AuthContext, Depends(require_user)], db: DB, request: Request
) -> AuthContext:
    from app.domains.access.authorization import require_global_admin

    return require_global_admin(db, context, lock=request.method not in {"GET", "HEAD", "OPTIONS"})


def require_manager(
    context: Annotated[AuthContext, Depends(require_user)], db: DB, request: Request
) -> AuthContext:
    from app.domains.access.authorization import require_manager as authorize

    return authorize(db, context, lock=request.method not in {"GET", "HEAD", "OPTIONS"})


def require_downloader(context: Annotated[AuthContext, Depends(require_user)]) -> AuthContext:
    if context.user.kind != "feishu":
        raise AppError(403, "FEISHU_LOGIN_REQUIRED", "请使用飞书账号登录下载")
    now = utcnow()
    until = context.session.eligibility_until
    if until is None or until <= now or (until - now).total_seconds() > 300:
        raise AppError(403, "ELIGIBILITY_UNVERIFIED", "飞书下载资格需重新验证")
    return context


def require_csrf(
    request: Request,
    context: Annotated[AuthContext, Depends(require_context)],
) -> AuthContext:
    origin = request.headers.get("origin")
    token = request.headers.get("x-csrf-token", "")
    if (
        origin != request.app.state.settings.site_url
        or len(token) > 200
        or not token
        or not secrets.compare_digest(token_hash(token), context.session.csrf_hash)
    ):
        raise AppError(403, "CSRF_INVALID", "请求来源或安全令牌无效")
    return context


def require_revision(if_match: str | None, revision: int) -> None:
    if if_match is None or not re.fullmatch(r'"(?:0|[1-9][0-9]*)"', if_match):
        raise AppError(422, "REVISION_REQUIRED", "请携带带双引号的 If-Match 版本")
    if int(if_match[1:-1]) != revision:
        raise AppError(412, "REVISION_MISMATCH", "数据已更新，请刷新后重试")


Admin = Annotated[AuthContext, Depends(require_admin)]
Manager = Annotated[AuthContext, Depends(require_manager)]
CSRF = Annotated[AuthContext, Depends(require_csrf)]
