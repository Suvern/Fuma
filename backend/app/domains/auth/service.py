import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Response
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.api.contracts import SessionResponse, SessionUser
from app.core.config import Settings
from app.core.errors import AppError
from app.domains.audit.service import record_audit
from app.domains.auth.models import AuthSession, RateBucket, User
from app.domains.system.models import SystemState

password_hasher = PasswordHasher()
initial_password_logger = logging.getLogger("fuma.initial_admin")


def initialize_admin(engine: Engine) -> None:
    """Create the first administrator once, serialized across API processes."""
    with Session(engine) as db:
        state = db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())
        if state is None:
            raise AppError(503, "DATABASE_NOT_INITIALIZED", "请先执行数据库迁移")
        user = db.scalar(select(User).where(User.username == "admin"))
        if state.initialized_at is not None:
            if user is None or user.kind != "local" or not user.password_hash:
                raise AppError(503, "ADMIN_STATE_INVALID", "管理员状态异常，请由服务器操作员恢复")
            return
        if user is not None:
            raise AppError(503, "ADMIN_STATE_INVALID", "管理员状态异常，请由服务器操作员恢复")
        password = secrets.token_urlsafe(32)
        user = User(
            kind="local",
            username="admin",
            display_name="admin",
            password_hash=password_hasher.hash(password),
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        state.initialized_at = utcnow()
        record_audit(
            db,
            action="admin.initialize",
            resource_type="account",
            resource_id=str(user.id),
            actor_kind="system",
            request_id="api-startup",
            summary="首次启动创建管理员，首次登录必须修改密码",
        )
        db.commit()
    # Only the process that committed creation emits this one-time credential.
    initial_password_logger.warning(
        "Fuma 首次启动已创建管理员 admin；临时密码：%s；首次登录后必须修改密码。", password
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_for_token(token: str) -> str:
    return hashlib.sha256(("fuma-csrf:" + token).encode()).hexdigest()


def cookie_name(settings: Settings) -> str:
    return "__Host-fuma_session" if settings.cookie_secure else "fuma_session"


@dataclass
class AuthContext:
    session: AuthSession
    user: User | None


def user_dto(user: User) -> SessionUser:
    return SessionUser(
        id=user.id,
        kind=user.kind,
        display_name=user.display_name,
        role="admin" if user.kind == "local" else "downloader",
        tenant_key=user.tenant_key,
        must_change_password=user.must_change_password,
    )


def session_response(user: User, session: AuthSession, csrf: str) -> SessionResponse:
    return SessionResponse(user=user_dto(user), csrf_token=csrf, expires_at=session.expires_at)


def create_user_session(
    db: Session,
    response: Response,
    user: User | None,
    settings: Settings,
    *,
    old_session: AuthSession | None = None,
    eligibility_until: datetime | None = None,
    config_revision: int | None = None,
) -> tuple[AuthSession, str]:
    now = utcnow()
    if old_session is not None:
        old_session.revoked_at = now
    raw = secrets.token_urlsafe(32)
    csrf = csrf_for_token(raw)
    kind = user.kind if user else "anonymous"
    if eligibility_until is not None:
        eligibility_until = min(eligibility_until, now + timedelta(seconds=300))
    session = AuthSession(
        token_hash=token_hash(raw),
        csrf_hash=token_hash(csrf),
        user_id=user.id if user else None,
        kind=kind,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds if user else 3600),
        authenticated_at=now if user else None,
        eligibility_until=eligibility_until,
        feishu_config_revision=config_revision,
    )
    db.add(session)
    db.flush()
    response.set_cookie(
        cookie_name(settings),
        raw,
        max_age=settings.session_ttl_seconds if user else 3600,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return session, csrf


def verify_password(encoded: str | None, password: str) -> bool:
    try:
        return bool(encoded and password_hasher.verify(encoded, password))
    except (VerificationError, InvalidHashError):
        return False


def rate_limit(db: Session, key: str, *, limit: int = 10, window: int = 300) -> None:
    """Shared, durable limit. Commit attempts before expensive password work."""
    digest = token_hash(key)
    lock = int(digest[:15], 16)
    db.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})
    row = db.get(RateBucket, digest)
    now = utcnow()
    if row is None:
        row = RateBucket(key=digest, window_start=now, attempts=0)
        db.add(row)
    elif row.window_start + timedelta(seconds=window) <= now:
        row.window_start, row.attempts = now, 0
    row.attempts += 1
    denied = row.attempts > limit
    db.commit()
    if denied:
        raise AppError(429, "RATE_LIMITED", "尝试过于频繁，请稍后重试", retryable=True)


def revoke_user_sessions(db: Session, user_id) -> None:
    for session in db.scalars(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    ):
        session.revoked_at = utcnow()
