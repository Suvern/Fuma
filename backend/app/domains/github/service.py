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
        github_login=row.github_login,
        last_tested_at=row.last_tested_at,
        last_test_status=row.last_test_status,
        last_error_code=row.last_error_code,
    )


def test_connection(
    client: GitHubClient, full_name: str | None, actions: bool
) -> tuple[list[Check], str | None]:
    checks, login = [], None
    try:
        identity = client.get_identity()
        login = str(identity["login"])
        checks.append(Check(code="identity", status="pass", message="GitHub 身份验证通过"))
    except (GitHubError, KeyError) as exc:
        checks.append(
            Check(
                code="identity",
                status="fail",
                message=(exc.message if isinstance(exc, GitHubError) else "无法验证 GitHub 身份"),
            )
        )
        return checks, login
    if full_name:
        try:
            client.get_repository(full_name)
            releases = client._json("/repos/" + full_name + "/releases", params={"per_page": 1})
            if not isinstance(releases, list):
                raise GitHubError("GITHUB_INVALID_RESPONSE", "Release 返回格式不合法")
            checks.append(Check(code="contents", status="pass", message="仓库 Release 可读取"))
            if releases:
                client.list_assets(full_name, releases[0]["id"])
                checks.append(Check(code="assets", status="pass", message="Release 附件列表可读取"))
            else:
                checks.append(
                    Check(
                        code="assets",
                        status="unknown",
                        message="仓库暂无 Release，需发布附件后验证",
                    )
                )
        except (GitHubError, KeyError) as exc:
            checks.append(
                Check(
                    code="contents",
                    status="fail",
                    message=(exc.message if isinstance(exc, GitHubError) else "附件返回格式不合法"),
                )
            )
        if actions:
            try:
                client.check_actions(full_name)
                checks.append(Check(code="actions", status="pass", message="构建记录可读取"))
            except GitHubError as exc:
                checks.append(Check(code="actions", status="fail", message=exc.message))
    else:
        checks.append(
            Check(code="contents", status="unknown", message="请选择仓库以验证 Release 和附件权限")
        )
        if actions:
            checks.append(
                Check(code="actions", status="unknown", message="请选择仓库以验证 Actions 只读权限")
            )
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
        # Recheck current configuration after the network round trip, before switching snapshots.
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
