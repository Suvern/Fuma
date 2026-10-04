from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update

from app.api.contracts import OwnSessionPage, SessionRevocation
from app.api.dependencies import CSRF, DB, require_user
from app.domains.audit.service import record_audit
from app.domains.auth.models import AuthSession
from app.domains.auth.service import AuthContext, utcnow

router = APIRouter(prefix="/auth/sessions", tags=["auth"])
CurrentUser = Annotated[AuthContext, Depends(require_user)]


@router.get("", response_model=OwnSessionPage, operation_id="list_own_sessions")
def list_own_sessions(
    db: DB,
    context: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    now = utcnow()
    query = select(AuthSession).where(AuthSession.user_id == context.user.id)
    rows = db.scalars(
        query.order_by(
            (AuthSession.id == context.session.id).desc(),
            AuthSession.created_at.desc(),
            AuthSession.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": db.scalar(select(func.count()).select_from(query.subquery())),
        "items": [
            {
                "id": row.id,
                "kind": row.kind,
                "created_at": row.created_at,
                "authenticated_at": row.authenticated_at,
                "expires_at": row.expires_at,
                "revoked_at": row.revoked_at,
                "current": row.id == context.session.id,
                "state": "revoked"
                if row.revoked_at
                else "expired"
                if row.expires_at <= now
                else "active",
            }
            for row in rows
        ],
    }


@router.post(
    "/revoke-others", response_model=SessionRevocation, operation_id="revoke_other_sessions"
)
def revoke_other_sessions(request: Request, db: DB, context: CurrentUser, csrf: CSRF):
    now = utcnow()
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == context.user.id,
            AuthSession.id != context.session.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .values(revoked_at=now)
    )
    count = result.rowcount
    record_audit(
        db,
        action="account.revoke_other_sessions",
        resource_type="account",
        resource_id=str(context.user.id),
        actor_id=str(context.user.id),
        actor_kind="feishu" if context.user.kind == "feishu" else "admin",
        request_id=request.state.request_id,
        summary=f"注销其他活动会话 {count} 个",
    )
    db.commit()
    return {"revoked_count": count}
