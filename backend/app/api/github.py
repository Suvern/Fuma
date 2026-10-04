import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, select, text

from app.api.applications import app_dto, get_app
from app.api.contracts import (
    App,
    ConnectionTestRequest,
    ConnectionTestResult,
    Connector,
    ConnectorCreate,
    ConnectorPage,
    ConnectorUpdate,
    GitHubAppCreate,
    GitHubAppCredentials,
    GitHubRelease,
    GitHubRepository,
    ReleaseImportPreview,
    ReleaseImportRequest,
    ReleaseMatchRules,
    ReleasePage,
    ReleasePolicy,
    ReleasePolicyUpdate,
    RepositoryBindRequest,
    RepositoryPage,
    TaskAccepted,
)
from app.api.dependencies import DB, require_admin, require_csrf, require_revision
from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.audit.service import record_audit
from app.domains.auth.service import AuthContext, utcnow
from app.domains.distribution.models import DebugRecord, RuleRecord
from app.domains.distribution.service import enqueue, idem_begin, idem_save, task_accepted
from app.domains.github.crypto import SecretBox
from app.domains.github.models import (
    GithubConnector,
    GithubConnectorCreation,
    GithubReleasePolicy,
    GithubRepositorySync,
)
from app.domains.github.releases import (
    get_policy,
    match_snapshot,
    policy_dto,
    preview_import,
    validate_rules,
)
from app.domains.github.service import (
    connector_dto,
    get_connector,
    get_github_client,
    test_connection,
)
from app.integrations.github import GitHubClient
from app.integrations.github_app import GitHubAppClient

router = APIRouter(tags=["github"], dependencies=[Depends(require_admin)])
Admin = Annotated[AuthContext, Depends(require_admin)]


def audit(db, request, context, action, resource):
    record_audit(
        db,
        action=action,
        resource_type="github",
        resource_id=str(resource),
        actor_id=str(context.user.id),
        request_id=request.state.request_id,
    )


def etag(response, row):
    response.headers["ETag"] = f'"{row.revision}"'


@router.get(
    "/connectors/github", response_model=ConnectorPage, operation_id="list_github_connectors"
)
def list_connectors(
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
):
    stmt = select(GithubConnector)
    if q:
        stmt = stmt.where(GithubConnector.name.icontains(q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(GithubConnector.created_at.desc(), GithubConnector.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return ConnectorPage(
        items=[connector_dto(row) for row in rows], page=page, page_size=page_size, total=total
    )


@router.post(
    "/connectors/github",
    response_model=Connector,
    status_code=201,
    operation_id="create_github_connectors",
    dependencies=[Depends(require_csrf)],
)
def create_connector(
    body: ConnectorCreate,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    idempotency_key: Annotated[UUID, Header()],
):
    if not body.name.strip() or ("enabled" in body.model_fields_set and body.enabled is None):
        raise AppError(422, "VALIDATION_ERROR", "名称或启用状态不合法")
    key = f"{context.user.id}:{idempotency_key}"
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int(hashlib.sha256(key.encode()).hexdigest()[:15], 16)},
    )
    previous = db.get(GithubConnectorCreation, key)
    if previous:
        if previous.body_hash != fingerprint:
            raise AppError(409, "IDEMPOTENCY_CONFLICT", "同一请求标识不能提交不同内容")
        row = get_connector(db, previous.connector_id)
        etag(response, row)
        return connector_dto(row)
    now, identity = utcnow(), uuid4()
    encrypted = SecretBox(request.app.state.settings).encrypt(body.token, "github:" + str(identity))
    row = GithubConnector(
        id=identity,
        name=body.name.strip(),
        encrypted_token=encrypted,
        enabled=True if body.enabled is None else body.enabled,
        revision=1,
        created_at=now,
        updated_at=now,
        last_test_status="untested",
    )
    db.add(row)
    db.add(GithubConnectorCreation(key=key, body_hash=fingerprint, connector_id=identity))
    audit(db, request, context, "github.create", identity)
    db.commit()
    etag(response, row)
    return connector_dto(row)


@router.get(
    "/connectors/github/{id}", response_model=Connector, operation_id="get_github_connectors"
)
def read_connector(id: UUID, response: Response, db: DB):
    row = get_connector(db, id)
    etag(response, row)
    return connector_dto(row)


@router.patch(
    "/connectors/github/{id}",
    response_model=Connector,
    operation_id="update_github_connectors",
    dependencies=[Depends(require_csrf)],
)
def update_connector(
    id: UUID,
    body: ConnectorUpdate,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    fields = body.model_dump(exclude_unset=True)
    if (
        not fields
        or any(value is None for value in fields.values())
        or ("name" in fields and not fields["name"].strip())
    ):
        raise AppError(422, "VALIDATION_ERROR", "更新字段不能为空")
    row = get_connector(db, id, lock=True)
    require_revision(if_match, row.revision)
    if "token" in fields:
        if row.auth_kind != "pat":
            raise AppError(422, "CREDENTIAL_TYPE_MISMATCH", "GitHub App 请使用 App 凭据轮换入口")
        # Verify the candidate before replacing the last usable credential.
        candidate = fields.pop("token")
        with GitHubClient(candidate) as client:
            identity = client.get_identity()
            row.encrypted_token = SecretBox(request.app.state.settings).encrypt(
                candidate, "github:" + str(row.id)
            )
            row.github_login = str(identity.get("login", ""))
            row.last_test_status, row.last_tested_at, row.last_error_code = "ok", utcnow(), None
    for name, value in fields.items():
        setattr(row, name, value.strip() if name == "name" else value)
    row.revision, row.updated_at = row.revision + 1, utcnow()
    audit(db, request, context, "github.update", id)
    db.commit()
    etag(response, row)
    return connector_dto(row)


@router.delete(
    "/connectors/github/{id}",
    status_code=204,
    operation_id="delete_github_connector",
    dependencies=[Depends(require_csrf)],
)
def delete_connector(
    id: UUID,
    request: Request,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    row = get_connector(db, id, lock=True)
    require_revision(if_match, row.revision)
    referenced = any(
        app.repository and app.repository.get("connector_id") == str(id)
        for app in db.scalars(select(AppRecord))
    )
    referenced = referenced or db.scalar(
        select(func.count()).select_from(DebugRecord).where(DebugRecord.connector_id == id)
    )
    if referenced:
        raise AppError(409, "CONNECTOR_IN_USE", "Connector 已有关联来源，请停用而非删除")
    audit(db, request, context, "github.delete", id)
    db.delete(row)
    db.commit()


@router.post(
    "/connectors/github/{id}/test",
    response_model=ConnectionTestResult,
    operation_id="test_github_connector",
    dependencies=[Depends(require_csrf)],
)
def run_connection_test(
    id: UUID, body: ConnectionTestRequest, request: Request, db: DB, context: Admin
):
    row = get_connector(db, id, lock=True)
    with get_github_client(db, id, request.app.state.settings) as client:
        checks, login = test_connection(client, body.repository_full_name, bool(body.check_actions))
    statuses = {check.status for check in checks}
    status = "failed" if "fail" in statuses else "partial" if "unknown" in statuses else "ok"
    row.github_login = login
    row.last_tested_at, row.last_test_status = utcnow(), "failed" if status == "failed" else "ok"
    row.last_error_code = "GITHUB_CHECK_FAILED" if status == "failed" else None
    audit(db, request, context, "github.test", id)
    db.commit()
    return ConnectionTestResult(status=status, checks=checks, tested_at=row.last_tested_at)


@router.get(
    "/connectors/github/{id}/repositories",
    response_model=RepositoryPage,
    operation_id="list_github_repositories",
)
def list_repositories(
    id: UUID,
    request: Request,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
):
    with get_github_client(db, id, request.app.state.settings) as client:
        rows = client.list_repositories()
    if q:
        rows = [row for row in rows if q.casefold() in row.get("full_name", "").casefold()]
    return RepositoryPage(
        items=[
            GitHubRepository(
                id=str(row["id"]),
                full_name=row["full_name"],
                private=row["private"],
                default_branch=row.get("default_branch") or "",
                contents_readable=bool(row.get("permissions", {}).get("pull", False)),
                actions_readable=None,
            )
            for row in rows[(page - 1) * page_size : page * page_size]
        ],
        page=page,
        page_size=page_size,
        total=len(rows),
    )


@router.put(
    "/apps/{id}/repository",
    response_model=App,
    operation_id="bind_app_repository",
    dependencies=[Depends(require_csrf)],
)
def bind_repository(
    id: UUID,
    body: RepositoryBindRequest,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    # Serialize with deletion/rotation so the JSON binding cannot reference a deleted connector.
    get_connector(db, body.connector_id, lock=True)
    app = get_app(db, id, lock=True)
    require_revision(if_match, app.revision)
    with get_github_client(db, body.connector_id, request.app.state.settings) as client:
        source = client.get_repository(body.full_name)
    binding = {
        "connector_id": str(body.connector_id),
        "repository_id": str(source["id"]),
        "full_name": source["full_name"],
        "private": source["private"],
    }
    if binding != app.repository:
        for model in (DebugRecord, RuleRecord):
            if db.scalar(select(func.count()).select_from(model).where(model.app_id == id)):
                raise AppError(
                    409, "REPOSITORY_IN_USE", "已有条目或 Actions 规则，不能更换仓库来源"
                )
        app.repository = binding
        snapshot = db.get(GithubRepositorySync, id)
        if snapshot:
            db.delete(snapshot)
        policy = db.get(GithubReleasePolicy, id)
        if policy:
            db.delete(policy)
    app.revision, app.updated_at = app.revision + 1, utcnow()
    audit(db, request, context, "github.repository.bind", id)
    db.commit()
    etag(response, app)
    return app_dto(db, app)


@router.get(
    "/apps/{id}/github/releases", response_model=ReleasePage, operation_id="list_github_releases"
)
def list_releases(
    id: UUID,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    prerelease: Literal["all", "only", "exclude"] = "all",
    asset_name: str | None = Query(None, max_length=255),
):
    app = get_app(db, id)
    if not app.repository:
        raise AppError(409, "REPOSITORY_NOT_BOUND", "请先关联 GitHub 仓库")
    state = db.get(GithubRepositorySync, id)
    rows = state.releases if state else []
    if prerelease != "all":
        rows = [row for row in rows if row["prerelease"] == (prerelease == "only")]
    if q:
        needle = q.casefold()
        rows = [
            row
            for row in rows
            if any(
                needle in str(text).casefold()
                for text in (
                    row["name"],
                    row["tag_name"],
                    *[asset["name"] for asset in row["assets"]],
                )
            )
        ]
    if asset_name:
        rows = [
            row
            for row in rows
            if any(asset_name.casefold() in asset["name"].casefold() for asset in row["assets"])
        ]
    selected = [
        GitHubRelease.model_validate(row) for row in rows[(page - 1) * page_size : page * page_size]
    ]
    entries = list(db.scalars(select(DebugRecord).where(DebugRecord.app_id == id)))
    for release in selected:
        for asset in release.assets:
            for entry in entries:
                source = entry.source
                if (
                    str(source["asset_id"]) == asset.id
                    and str(source["release_id"]) == release.id
                    and source["size_bytes"] == asset.size_bytes
                    and source.get("digest") == asset.digest
                    and datetime.fromisoformat(source["asset_updated_at"].replace("Z", "+00:00"))
                    == asset.updated_at
                    and entry.file_name == asset.name
                ):
                    asset.debug_entry_id, asset.cache_state = entry.id, entry.cache_state
                    break
    return ReleasePage(
        items=selected,
        page=page,
        page_size=page_size,
        total=len(rows),
        synced_at=state.synced_at if state else None,
        sync_state=state.state if state else "never",
        sync_error_code=state.error_code if state else None,
    )


@router.post(
    "/apps/{id}/github/releases/refresh",
    response_model=TaskAccepted,
    status_code=202,
    operation_id="refresh_github_releases",
    dependencies=[Depends(require_csrf)],
)
def refresh_releases(
    id: UUID, request: Request, db: DB, context: Admin, idempotency_key: Annotated[UUID, Header()]
):
    app = get_app(db, id, lock=True)
    if not app.repository or not app.enabled:
        raise AppError(409, "REPOSITORY_NOT_BOUND", "App 未启用或尚未关联仓库")
    get_github_client(db, app.repository["connector_id"], request.app.state.settings).close()
    scope, previous = idem_begin(
        db, f"release-refresh:{context.user.id}:{id}", str(idempotency_key), {}
    )
    if previous:
        return previous.data
    policy = db.get(GithubReleasePolicy, id)
    task = enqueue(
        db,
        "release_sync",
        resource_id=str(id),
        app_id=id,
        dedupe_key=f"release_sync:{id}",
        payload={"policy_revision": policy.revision} if policy and policy.auto_enabled else {},
    )
    if policy:
        policy.last_task_id = task.id
    result = task_accepted(task)
    idem_save(db, scope, {}, result)
    audit(db, request, context, "github.releases.refresh", id)
    db.commit()
    return result


@router.get(
    "/apps/{id}/github/releases/policy",
    response_model=ReleasePolicy,
    operation_id="get_release_policy",
)
def release_policy(id: UUID, db: DB, response: Response):
    result = policy_dto(db, get_app(db, id))
    response.headers["ETag"] = f'"{result["revision"]}"'
    return result


@router.put(
    "/apps/{id}/github/releases/policy",
    response_model=ReleasePolicy,
    operation_id="update_release_policy",
    dependencies=[Depends(require_csrf)],
)
def update_release_policy(
    id: UUID,
    body: ReleasePolicyUpdate,
    request: Request,
    response: Response,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    app = get_app(db, id, lock=True)
    if not app.repository:
        raise AppError(409, "REPOSITORY_NOT_BOUND", "请先关联 GitHub 仓库")
    rules = validate_rules(body.rules.model_dump(mode="json"))
    if body.auto_enabled:
        if not app.enabled:
            raise AppError(409, "APP_NOT_READY", "请先启用应用")
        get_github_client(db, app.repository["connector_id"], request.app.state.settings).close()
    row = get_policy(db, id)
    require_revision(if_match, row.revision)
    row.settings = rules
    row.auto_enabled = body.auto_enabled
    row.interval_minutes = body.interval_minutes
    row.next_check_at = utcnow() if body.auto_enabled else None
    row.revision += 1
    audit(db, request, context, "github.release_policy.update", id)
    db.commit()
    return release_policy(id, db, response)


@router.post(
    "/apps/{id}/github/releases/preview",
    response_model=ReleaseImportPreview,
    operation_id="preview_release_import",
    dependencies=[Depends(require_csrf)],
)
def preview_release_import(id: UUID, body: ReleaseMatchRules, db: DB):
    result = preview_import(db, get_app(db, id), body.model_dump(mode="json"))
    db.commit()
    return result


@router.post(
    "/apps/{id}/github/releases/import",
    response_model=TaskAccepted,
    status_code=202,
    operation_id="import_release_matches",
    dependencies=[Depends(require_csrf)],
)
def import_release_matches(
    id: UUID,
    body: ReleaseImportRequest,
    request: Request,
    db: DB,
    context: Admin,
    idempotency_key: Annotated[UUID, Header()],
):
    payload = body.model_dump(mode="json")
    scope, previous = idem_begin(
        db, f"release-import:{context.user.id}:{id}", str(idempotency_key), payload
    )
    if previous:
        return previous.data
    app = get_app(db, id)
    row = get_policy(db, id)
    _, matches, _, token = match_snapshot(db, app, payload["rules"])
    if body.snapshot_token != token:
        raise AppError(409, "RELEASE_PREVIEW_STALE", "Release 或规则已变化，请重新预览")
    if not matches:
        raise AppError(422, "NO_MATCHING_ASSETS", "没有匹配的安装包")
    get_github_client(db, app.repository["connector_id"], request.app.state.settings).close()
    task = enqueue(
        db,
        "release_import",
        app_id=id,
        resource_id=str(id),
        payload={"matches": matches, "binding": app.repository},
        dedupe_key=f"release_import:{id}:{token}",
    )
    row.last_task_id = task.id
    result = task_accepted(task)
    idem_save(db, scope, payload, result)
    audit(db, request, context, "github.releases.import.enqueue", id)
    db.commit()
    return result


@router.post(
    "/connectors/github-app",
    response_model=Connector,
    operation_id="create_github_app",
    dependencies=[Depends(require_csrf)],
)
def create_github_app(body: GitHubAppCreate, request: Request, db: DB, context: Admin):
    if not body.name.strip():
        raise AppError(422, "VALIDATION_ERROR", "名称不能为空")
    credentials = body.model_dump(exclude={"name"})
    with GitHubAppClient(credentials) as client:
        identity = client.get_identity()
    now, id = utcnow(), uuid4()
    row = GithubConnector(
        id=id,
        name=body.name.strip(),
        auth_kind="github_app",
        app_id=body.app_id,
        installation_id=body.installation_id,
        encrypted_token=SecretBox(request.app.state.settings).encrypt(
            json.dumps(credentials), "github:" + str(id)
        ),
        enabled=True,
        revision=1,
        created_at=now,
        updated_at=now,
        github_login=identity["login"],
        last_test_status="ok",
        last_tested_at=now,
    )
    db.add(row)
    audit(db, request, context, "github.app_create", id)
    db.commit()
    return connector_dto(row)


@router.put(
    "/connectors/github/{id}/app-credentials",
    response_model=Connector,
    operation_id="rotate_github_app",
    dependencies=[Depends(require_csrf)],
)
def rotate_github_app(
    id: UUID,
    body: GitHubAppCredentials,
    request: Request,
    db: DB,
    context: Admin,
    if_match: Annotated[str | None, Header()] = None,
):
    row = get_connector(db, id, lock=True)
    require_revision(if_match, row.revision)
    if (
        row.auth_kind != "github_app"
        or body.app_id != row.app_id
        or body.installation_id != row.installation_id
    ):
        raise AppError(
            409,
            "GITHUB_INSTALLATION_IMMUTABLE",
            "App 与安装实例固定，变更请新建连接；此处只轮换同实例私钥",
        )
    credentials = body.model_dump()
    with GitHubAppClient(credentials) as client:
        identity = client.get_identity()
    row.encrypted_token = SecretBox(request.app.state.settings).encrypt(
        json.dumps(credentials), "github:" + str(id)
    )
    row.github_login, row.last_test_status, row.last_tested_at, row.last_error_code = (
        identity["login"],
        "ok",
        utcnow(),
        None,
    )
    row.revision, row.updated_at = row.revision + 1, utcnow()
    audit(db, request, context, "github.app_rotate", id)
    db.commit()
    return connector_dto(row)
