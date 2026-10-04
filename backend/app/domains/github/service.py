import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.contracts import Check, Connector, GitHubAsset, GitHubRelease
from app.core.config import Settings
from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.auth.service import utcnow
from app.domains.github.crypto import SecretBox
from app.domains.github.models import GithubConnector, GithubRepositorySync
from app.integrations.github import GitHubClient, GitHubError


def get_connector(db: Session, connector_id: UUID | str, *, lock: bool = False) -> GithubConnector:
    query = select(GithubConnector).where(GithubConnector.id == UUID(str(connector_id)))
    query = query.execution_options(populate_existing=True)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise AppError(404, "CONNECTOR_NOT_FOUND", "GitHub Connector 不存在")
    return row


def get_github_client(db: Session, connector_id: UUID | str, settings: Settings) -> GitHubClient:
    row = get_connector(db, connector_id)
    if not row.enabled:
        raise AppError(409, "CONNECTOR_DISABLED", "GitHub Connector 已停用")
    token = SecretBox(settings).decrypt(row.encrypted_token, "github:" + str(row.id))
    if row.auth_kind == "github_app":
        from app.integrations.github_app import GitHubAppClient

        return GitHubAppClient(json.loads(token), cache_key=(str(row.id), row.revision))
    return GitHubClient(token)


def connector_dto(row: GithubConnector) -> Connector:
    return Connector(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        revision=row.revision,
        name=row.name,
        enabled=row.enabled,
        has_token=bool(row.encrypted_token),
        auth_kind=row.auth_kind,
        app_id=row.app_id,
        installation_id=row.installation_id,
        github_login=row.github_login,
        last_tested_at=row.last_tested_at,
        last_test_status=row.last_test_status,
        last_error_code=row.last_error_code,
    )


def connection_failure(code: str, exc: GitHubError, endpoint: str) -> Check:
    permissions = {
        "repository": "Metadata · Read-only",
        "contents": "Contents · Read-only",
        "assets": "Contents · Read-only",
        "actions": "Actions · Read-only",
    }
    subjects = {
        "identity": "GitHub 身份验证",
        "repository": "仓库访问",
        "contents": "Release 列表读取",
        "assets": "Release 附件列表读取",
        "actions": "Actions 构建记录读取",
    }
    permission = permissions.get(code)
    remediation = "稍后重新检查；如果持续失败，请检查服务端到 GitHub 的网络连接。"
    message = exc.message
    if exc.code == "GITHUB_FORBIDDEN":
        message = f"{subjects[code]}被 GitHub 拒绝（403）"
        remediation = (
            "在 GitHub 中编辑此令牌，确认 Repository access 包含目标仓库"
            + (f"，并在 Repository permissions 中开启 {permission}" if permission else "")
            + "。若配置已正确，请检查组织审批、SSO 授权或组织访问策略。GitHub 未返回唯一拒绝原因。"
        )
    elif exc.code == "GITHUB_SSO_REQUIRED":
        remediation = "在 GitHub 的令牌设置中完成组织 SSO 授权，再重新检查。"
    elif exc.code == "GITHUB_BAD_CREDENTIAL":
        remediation = "检查令牌是否已过期或撤销；在「编辑连接」中替换令牌后重新检查。"
    elif exc.code == "GITHUB_NOT_FOUND":
        message = f"{subjects[code]}不可用（404）：资源不存在或此令牌不可见"
        remediation = (
            "核对仓库完整名称，并确认令牌的 Resource owner 与 Repository access 包含该仓库。"
            "私有资源无权访问时也可能返回 404，无法仅凭此响应判断资源是否存在。"
        )
    elif exc.code == "GITHUB_RATE_LIMITED":
        remediation = f"GitHub 请求已限流，请至少等待 {exc.retry_after or 60} 秒再重新检查。"
    elif exc.code == "GITHUB_SOURCE_MOVED":
        remediation = "仓库可能已改名或转移，请填写新的仓库完整名称后重新检查。"
    elif exc.code == "GITHUB_INVALID_RESPONSE":
        remediation = "GitHub 返回的数据不完整，请重新检查；持续失败时联系管理员。"
    return Check(
        code=code,
        status="fail",
        message=message,
        error_code=exc.code,
        required_permission=permission
        if exc.code in {"GITHUB_FORBIDDEN", "GITHUB_NOT_FOUND"}
        else None,
        remediation=remediation,
        endpoint=endpoint,
    )


def test_connection(
    client: GitHubClient, full_name: str | None, actions: bool
) -> tuple[list[Check], str | None]:
    checks, login = [], None
    try:
        identity = client.get_identity()
        login = str(identity["login"])
        checks.append(Check(code="identity", status="pass", message=f"已验证 GitHub 账号 {login}"))
    except (GitHubError, KeyError) as exc:
        error = (
            exc
            if isinstance(exc, GitHubError)
            else GitHubError("GITHUB_INVALID_RESPONSE", "无法验证 GitHub 身份")
        )
        checks.append(connection_failure("identity", error, "GET /user"))
        for code in ["repository", "contents", "assets"] + (["actions"] if actions else []):
            checks.append(Check(code=code, status="unknown", message="身份验证未通过，尚未检查"))
        return checks, login

    if not full_name:
        for code in ["repository", "contents", "assets"] + (["actions"] if actions else []):
            checks.append(Check(code=code, status="unknown", message="填写目标仓库后可检查此项"))
        return checks, login

    base = "/repos/" + full_name
    try:
        client.get_repository(full_name)
        checks.append(Check(code="repository", status="pass", message=f"可访问 {full_name}"))
    except GitHubError as exc:
        checks.append(connection_failure("repository", exc, "GET " + base))
        for code in ["contents", "assets"] + (["actions"] if actions else []):
            checks.append(Check(code=code, status="unknown", message="仓库不可访问，尚未检查"))
        return checks, login

    releases = None
    try:
        releases = client._json(base + "/releases", params={"per_page": 1})
        if not isinstance(releases, list):
            raise GitHubError("GITHUB_INVALID_RESPONSE", "Release 返回格式不合法")
        checks.append(Check(code="contents", status="pass", message="可读取 Release 列表"))
    except GitHubError as exc:
        releases = None
        checks.append(connection_failure("contents", exc, "GET " + base + "/releases"))

    if releases:
        endpoint = "GET " + base + "/releases/{release_id}/assets"
        try:
            client.list_assets(full_name, releases[0]["id"])
            checks.append(
                Check(
                    code="assets",
                    status="pass",
                    message="可读取附件列表；实际下载将在同步安装包时验证",
                )
            )
        except (GitHubError, KeyError, TypeError) as exc:
            error = (
                exc
                if isinstance(exc, GitHubError)
                else GitHubError("GITHUB_INVALID_RESPONSE", "Release 附件数据不完整")
            )
            checks.append(connection_failure("assets", error, endpoint))
    else:
        checks.append(
            Check(
                code="assets",
                status="unknown",
                message="仓库暂无 Release，发布后可验证附件列表"
                if releases == []
                else "Release 列表未读取，尚未检查附件",
            )
        )
    if actions:
        try:
            client.check_actions(full_name)
            checks.append(Check(code="actions", status="pass", message="可读取 Actions 构建记录"))
        except GitHubError as exc:
            checks.append(connection_failure("actions", exc, "GET " + base + "/actions/runs"))
    return checks, login


def release_dto(row: dict) -> GitHubRelease:
    try:
        assets = []
        for asset in row.get("assets", []):
            name = str(asset["name"])
            suffix = name.rsplit(".", 1)[-1].lower()
            platform = {"apk": "android", "ipa": "ios"}.get(suffix)
            assets.append(
                GitHubAsset(
                    id=str(asset["id"]),
                    name=name,
                    size_bytes=asset["size"],
                    content_type=asset.get("content_type") or "application/octet-stream",
                    updated_at=asset["updated_at"],
                    digest=asset.get("digest"),
                    supported=platform is not None and not row.get("draft", False),
                    platform=platform,
                    debug_entry_id=None,
                    cache_state="missing",
                )
            )
        return GitHubRelease(
            id=str(row["id"]),
            name=row.get("name") or row.get("tag_name") or "未命名 Release",
            tag_name=row["tag_name"],
            body=(row.get("body") or "")[:20000],
            draft=row["draft"],
            prerelease=row["prerelease"],
            published_at=row.get("published_at"),
            assets=assets,
        )
    except (KeyError, TypeError, ValueError):
        raise GitHubError("GITHUB_INVALID_RESPONSE", "GitHub Release 元数据不完整") from None


def sync_releases(db: Session, app_id: UUID | str, settings: Settings) -> None:
    app = db.get(AppRecord, UUID(str(app_id)))
    if app is None or not app.enabled or not app.repository:
        raise AppError(409, "REPOSITORY_NOT_BOUND", "App 未启用或尚未关联仓库")
    binding = dict(app.repository)
    state = db.get(GithubRepositorySync, app.id)
    if state is None:
        state = GithubRepositorySync(
            app_id=app.id, repository_id=binding["repository_id"], releases=[], state="never"
        )
        db.add(state)
    state.state, state.error_code = "syncing", None
    db.commit()
    try:
        with get_github_client(db, binding["connector_id"], settings) as client:
            repository = client.get_repository(binding["full_name"])
            if str(repository["id"]) != binding["repository_id"]:
                raise GitHubError("SOURCE_CHANGED", "仓库身份已变化，请重新确认关联", 409)
            snapshot = [
                release_dto(row).model_dump(mode="json")
                for row in client.list_releases(binding["full_name"])
            ]
        # Recheck current authority before acquiring the App lock and switching snapshots.
        from app.domains.access.task_authorization import check_task_authorization

        check_task_authorization(db)
        db.refresh(app, with_for_update=True)
        if not app.enabled or app.repository != binding:
            raise AppError(409, "SOURCE_CHANGED", "同步期间仓库关联或 App 状态发生变化")
        get_github_client(db, binding["connector_id"], settings).close()
        state.releases = snapshot
        state.state, state.error_code, state.synced_at = "ready", None, utcnow()
        db.commit()
    except AppError as exc:
        db.rollback()
        state = db.get(GithubRepositorySync, app.id)
        if state is not None:
            state.state, state.error_code = "failed", exc.code
            db.commit()
        raise
