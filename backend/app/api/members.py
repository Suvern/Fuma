"""Global administrators manage explicit, currently scoped member authority."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import delete, select

from app.api import contracts as dto
from app.api.dependencies import CSRF, DB, Admin, require_revision
from app.core.errors import AppError
from app.domains.access.authorization import assigned_app_ids, identity_verified, is_rescue_admin
from app.domains.applications.models import AppRecord
from app.domains.audit.service import record_audit
from app.domains.auth.models import AppRoleRecord, RoleChangeRecord, User
from app.domains.auth.service import revoke_user_sessions, utcnow
from app.domains.distribution.service import must_get, page, state

router = APIRouter(tags=["Access"])


def member_dto(db, user):
    return dict(
        id=user.id,
        kind=user.kind,
        display_name=user.display_name,
        tenant_key=user.tenant_key,
        provider_app_id=user.provider_app_id,
        open_id=user.open_id,
        role="admin" if is_rescue_admin(user) else user.global_role,
        managed_app_ids=sorted(assigned_app_ids(db, user), key=str),
        active=user.active,
        permission_revision=user.permission_revision,
        identity_verified=identity_verified(db, user),
        permission_changed_at=user.permission_changed_at,
    )


@router.get("/settings/members", response_model=dto.MemberPage, operation_id="list_members")
def members(
    db: DB,
    admin: Admin,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    role: Literal["admin", "maintainer", "downloader"] | None = None,
    app_id: UUID | None = None,
    active: bool | None = None,
):
    rows = db.scalars(select(User).order_by(User.display_name, User.id))
    keyword = (q or "").strip().casefold()
    result = []
    for user in rows:
        item = member_dto(db, user)
        if role and item["role"] != role or active is not None and user.active != active:
            continue
        if app_id and item["role"] != "admin" and app_id not in item["managed_app_ids"]:
            continue
        if (
            keyword
            and keyword
            not in " ".join([user.display_name, user.username or "", user.open_id or ""]).casefold()
        ):
            continue
        result.append(item)
    return page(result, page_number, page_size)


@router.put(
    "/settings/members/{id}/roles",
    response_model=dto.MemberInfo,
    operation_id="update_member_roles",
)
def update_roles(
    id: UUID,
    body: dto.MemberRolesUpdate,
    request: Request,
    db: DB,
    admin: Admin,
    csrf: CSRF,
    if_match: Annotated[str | None, Header()] = None,
):
    config = state(db, "feishu", locked=True)
    user = must_get(db, User, id)
    db.refresh(user, with_for_update=True)
    require_revision(if_match, user.permission_revision)
    if is_rescue_admin(user) or user.kind != "feishu":
        raise AppError(409, "RESCUE_ACCOUNT_IMMUTABLE", "内置本地管理员不能停用或修改授权")
    only_disabling = (
        not body.active
        and body.role == user.global_role
        and set(body.managed_app_ids) == assigned_app_ids(db, user)
    )
    if (
        body.role != "downloader"
        and not only_disabling
        and (not identity_verified(db, user, config) or not config.data.get("enabled"))
    ):
        raise AppError(409, "IDENTITY_NOT_VERIFIED", "请先使用当前绑定的飞书应用完成租户身份验证")
    app_ids = sorted(set(body.managed_app_ids), key=str)
    if (body.role == "maintainer" and not app_ids) or (body.role != "maintainer" and app_ids):
        raise AppError(
            422, "ROLE_SCOPE_INVALID", "维护者须选择至少一个App；其他角色不能配置App范围"
        )
    if len(app_ids) != len(body.managed_app_ids):
        raise AppError(422, "ROLE_SCOPE_INVALID", "App范围不能重复")
    for app_id in app_ids:
        app = db.scalar(select(AppRecord).where(AppRecord.id == app_id).with_for_update())
        if not app or app.archived_at:
            raise AppError(409, "APP_NOT_AVAILABLE", "授权App不存在或已归档")
    before = {
        "role": user.global_role,
        "active": user.active,
        "managed_app_ids": sorted(str(value) for value in assigned_app_ids(db, user)),
    }
    after = {
        "role": body.role,
        "active": body.active,
        "managed_app_ids": [str(value) for value in app_ids],
    }
    db.execute(delete(AppRoleRecord).where(AppRoleRecord.user_id == id))
    db.add_all(AppRoleRecord(user_id=id, app_id=app_id) for app_id in app_ids)
    user.global_role, user.active = body.role, body.active
    user.permission_revision += 1
    user.permission_changed_at = utcnow()
    if not user.active:
        revoke_user_sessions(db, id)
    change = RoleChangeRecord(
        user_id=id,
        actor_id=admin.user.id,
        permission_revision=user.permission_revision,
        before_rules=before,
        after_rules=after,
        created_at=user.permission_changed_at,
    )
    db.add(change)
    db.flush()
    record_audit(
        db,
        action="member.roles_updated",
        resource_type="member",
        resource_id=str(id),
        actor_kind="feishu" if admin.user.kind == "feishu" else "admin",
        actor_id=str(admin.user.id),
        request_id=request.state.request_id,
        summary=(
            f"授权修订 {user.permission_revision}；{before['role']} → {body.role}；"
            f"启用={body.active}；完整变更={change.id}"
        ),
    )
    db.commit()
    return member_dto(db, user)
