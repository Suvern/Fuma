from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app.api.contracts import (
    BootstrapStatus,
    BrowserContext,
    LoginRequest,
    PasswordRequest,
    SessionResponse,
)
from app.api.dependencies import (
    DB,
    optional_context,
    require_csrf,
    require_local_admin,
    require_user,
)
from app.core.errors import AppError
from app.domains.audit.service import record_audit
from app.domains.auth.models import User
from app.domains.auth.service import (
    AuthContext,
    cookie_name,
    create_user_session,
    csrf_for_token,
    password_hasher,
    rate_limit,
    revoke_user_sessions,
    session_response,
    user_dto,
    utcnow,
    verify_password,
)
from app.domains.system.models import SystemState

router = APIRouter(prefix="/auth", tags=["auth"])
CSRF = Annotated[AuthContext, Depends(require_csrf)]
Admin = Annotated[AuthContext, Depends(require_local_admin)]


def audit(db, request, action, user=None, outcome="success"):
    record_audit(
        db,
        action=action,
        resource_type="account",
        request_id=request.state.request_id,
        actor_id=str(user.id) if user else None,
        actor_kind="feishu" if user and user.kind == "feishu" else "admin" if user else "system",
        outcome=outcome,
    )


@router.get(
    "/bootstrap-status", response_model=BootstrapStatus, operation_id="get_bootstrap_status"
)
def bootstrap_status(request: Request, db: DB):
    state = db.get(SystemState, 1)
    checker = getattr(request.app.state, "sso_enabled", None)
    return BootstrapStatus(
        initialized=bool(state and state.initialized_at),
        sso_enabled=bool(checker(db)) if checker else False,
    )


@router.get("/browser-context", response_model=BrowserContext, operation_id="get_browser_context")
def browser_context(
    request: Request,
    response: Response,
    db: DB,
    context: Annotated[AuthContext | None, Depends(optional_context)],
):
    if context is None:
        session, csrf = create_user_session(db, response, None, request.app.state.settings)
        db.commit()
        context = AuthContext(session, None)
    else:
        csrf = csrf_for_token(request.cookies[cookie_name(request.app.state.settings)])
    return BrowserContext(
        authenticated=context.user is not None,
        eligibility_expires_at=context.session.eligibility_until
        if context.user and context.user.kind == "feishu"
        else None,
        viewer_key=str(context.session.id),
        csrf_token=csrf,
        user=user_dto(context.user) if context.user else None,
    )


@router.post("/login", response_model=SessionResponse, operation_id="login_admin")
def login(body: LoginRequest, request: Request, response: Response, db: DB, context: CSRF):
    rate_limit(db, "login:" + (request.client.host if request.client else "unknown"))
    user = db.scalar(
        select(User)
        .where(User.username == "admin")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or not verify_password(user.password_hash, body.password):
        audit(db, request, "login", outcome="failure")
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "账号或密码不正确")
    session, csrf = create_user_session(
        db, response, user, request.app.state.settings, old_session=context.session
    )
    audit(db, request, "login", user)
    db.commit()
    return session_response(user, session, csrf)


@router.get("/me", response_model=SessionResponse, operation_id="get_session")
def me(request: Request, context: Annotated[AuthContext, Depends(require_user)]):
    return session_response(
        context.user,
        context.session,
        csrf_for_token(request.cookies[cookie_name(request.app.state.settings)]),
    )


@router.post("/logout", status_code=204, operation_id="logout")
def logout(request: Request, response: Response, db: DB, context: CSRF):
    context.session.revoked_at = utcnow()
    audit(db, request, "logout", context.user)
    db.commit()
    response.delete_cookie(
        cookie_name(request.app.state.settings),
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/password",
    response_model=SessionResponse,
    operation_id="change_password",
    dependencies=[Depends(require_csrf)],
)
def password(body: PasswordRequest, request: Request, response: Response, db: DB, context: Admin):
    rate_limit(db, "password:" + str(context.user.id), limit=5)
    user = db.scalar(
        select(User)
        .where(User.id == context.user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not verify_password(user.password_hash, body.old_password):
        audit(db, request, "password", user, outcome="failure")
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "原密码不正确")
    if body.new_password == body.old_password:
        raise AppError(422, "PASSWORD_UNCHANGED", "新密码不能与原密码相同")
    user.password_hash = password_hasher.hash(body.new_password)
    user.must_change_password = False
    revoke_user_sessions(db, user.id)
    session, csrf = create_user_session(db, response, user, request.app.state.settings)
    audit(db, request, "password", user)
    db.commit()
    return session_response(user, session, csrf)
