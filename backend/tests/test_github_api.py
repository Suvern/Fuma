"""GitHub management API against isolated native PostgreSQL and injected provider HTTP."""

import base64
import secrets
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.github import router
from app.core.config import Settings
from app.domains.auth.models import User
from app.domains.auth.service import password_hasher, utcnow
from app.domains.github.models import GithubConnector, GithubRepositorySync
from app.domains.github.service import sync_releases
from app.domains.system.models import SystemState
from app.infrastructure.database import Base, build_engine
from app.integrations.github import GitHubClient, GitHubError
from app.main import create_app


def make_release(identity, name="debug.apk", prerelease=False):
    return {
        "id": identity,
        "name": f"Release {identity}",
        "tag_name": f"v{identity}",
        "draft": False,
        "prerelease": prerelease,
        "body": "Release notes",
        "published_at": "2026-10-01T00:00:00Z",
        "assets": [
            {
                "id": identity * 10,
                "name": name,
                "size": 4,
                "content_type": "application/zip",
                "updated_at": "2026-10-01T00:00:00Z",
            }
        ],
    }


@pytest.fixture
def github_client(monkeypatch, tmp_path):
    settings = Settings(
        database_url="postgresql+psycopg://fuma@127.0.0.1:55432/fuma_github_test",
        encryption_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        cache_dir=tmp_path,
        state_dir=tmp_path / "state",
    )
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception:
        engine.dispose()
        pytest.skip("isolated native PostgreSQL fuma_github_test unavailable")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(SystemState(id=1, initialized_at=utcnow()))
        db.add(
            User(
                kind="local",
                username="admin",
                display_name="admin",
                password_hash=password_hasher.hash("Test-password-123"),
            )
        )
        db.commit()
    provider = {"fail": False, "releases": [make_release(1), make_release(2, "preview.ipa", True)]}

    def handle(request):
        if (
            provider["fail"]
            or request.headers.get("authorization") == "Bearer invalid-candidate-token"
        ):
            return httpx.Response(403, json={"message": "not-exposed-private-detail"})
        path = request.url.path
        if path == "/user":
            return httpx.Response(200, json={"login": "fixture-owner"})
        if path == "/user/repos":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "full_name": "owner/private",
                        "private": True,
                        "default_branch": "main",
                        "permissions": {"pull": True},
                    }
                ],
            )
        if path.endswith("/releases"):
            page = int(request.url.params.get("page", 1))
            rows = provider["releases"][(page - 1) * 100 : page * 100]
            return httpx.Response(200, json=rows)
        if path.endswith("/assets"):
            release_id = int(path.split("/")[-2])
            row = next(row for row in provider["releases"] if row["id"] == release_id)
            return httpx.Response(200, json=row["assets"])
        if "/releases/" in path:
            release_id = int(path.rsplit("/", 1)[-1])
            row = next((r for r in provider["releases"] if r["id"] == release_id), None)
            return httpx.Response(200, json=row) if row else httpx.Response(404)
        if path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": []})
        return httpx.Response(200, json={"id": 7, "full_name": "owner/private", "private": True})

    def factory(token):
        return GitHubClient(token, transport=httpx.MockTransport(handle))

    monkeypatch.setattr("app.api.github.GitHubClient", factory)
    monkeypatch.setattr("app.domains.github.service.GitHubClient", factory)
    app = create_app(settings)
    if not any(getattr(route, "path", "") == "/api/v1/connectors/github" for route in app.routes):
        app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, provider
    engine.dispose()


def initialize(client):
    context = client.get("/api/v1/auth/browser-context").json()
    headers = {"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": context["csrf_token"]}
    response = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={
            "username": "admin",
            "password": "Test-password-123",
        },
    )
    assert response.status_code == 200, response.text
    headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return headers


def create_connector(client, headers):
    response = client.post(
        "/api/v1/connectors/github",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"name": "Primary", "token": "synthetic-provider-token"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_bound_app(client, headers, connector):
    response = client.post(
        "/api/v1/apps",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"name": "Sample", "public_slug": "sample", "platforms": ["android", "ios"]},
    )
    assert response.status_code == 201, response.text
    app = response.json()
    response = client.put(
        f"/api/v1/apps/{app['id']}/repository",
        headers={**headers, "If-Match": '"1"'},
        json={"connector_id": connector["id"], "full_name": "owner/private"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_connector_permissions_encryption_idempotency_and_rotation(github_client):
    client, _ = github_client
    assert client.get("/api/v1/connectors/github").status_code == 401
    headers = initialize(client)
    key = str(uuid4())
    body = {"name": "Primary", "token": "synthetic-provider-token"}
    assert client.post("/api/v1/connectors/github", json=body).status_code == 403
    result = client.post(
        "/api/v1/connectors/github", headers={**headers, "Idempotency-Key": key}, json=body
    )
    assert result.status_code == 201, result.text
    record = result.json()
    assert "synthetic-provider-token" not in result.text
    assert result.headers["etag"] == '"1"'
    repeat = client.post(
        "/api/v1/connectors/github", headers={**headers, "Idempotency-Key": key}, json=body
    )
    assert repeat.json()["id"] == record["id"]
    assert (
        client.post(
            "/api/v1/connectors/github",
            headers={**headers, "Idempotency-Key": key},
            json={**body, "name": "Different"},
        ).status_code
        == 409
    )
    with Session(client.app.state.engine) as db:
        before = db.get(GithubConnector, UUID(record["id"])).encrypted_token
        assert "synthetic-provider-token" not in before
    path = f"/api/v1/connectors/github/{record['id']}"
    failed = client.patch(
        path, headers={**headers, "If-Match": '"1"'}, json={"token": "invalid-candidate-token"}
    )
    assert failed.status_code == 403
    with Session(client.app.state.engine) as db:
        row = db.get(GithubConnector, UUID(record["id"]))
        assert row.encrypted_token == before
        assert row.revision == 1
    assert (
        client.patch(
            path, headers={**headers, "If-Match": '"1"'}, json={"enabled": None}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            path, headers={**headers, "If-Match": '"8"'}, json={"name": "Changed"}
        ).status_code
        == 412
    )
    good = client.patch(
        path, headers={**headers, "If-Match": '"1"'}, json={"token": "rotated-synthetic-token"}
    )
    assert good.status_code == 200, good.text
    assert good.headers["etag"] == '"2"'


def test_binding_test_refresh_and_complete_snapshot_search(github_client):
    client, provider = github_client
    headers = initialize(client)
    connector = create_connector(client, headers)
    test = client.post(
        f"/api/v1/connectors/github/{connector['id']}/test",
        headers=headers,
        json={"repository_full_name": "owner/private", "check_actions": True},
    )
    assert test.status_code == 200, test.text
    assert test.json()["status"] == "ok"
    assert {item["code"] for item in test.json()["checks"]} == {
        "identity",
        "repository",
        "contents",
        "assets",
        "actions",
    }
    app = create_bound_app(client, headers, connector)
    path = f"/api/v1/apps/{app['id']}/github/releases"
    assert client.get(path).json()["sync_state"] == "never"
    key = str(uuid4())
    refresh = client.post(path + "/refresh", headers={**headers, "Idempotency-Key": key})
    assert refresh.status_code == 202, refresh.text
    assert (
        client.post(path + "/refresh", headers={**headers, "Idempotency-Key": key}).json()
        == refresh.json()
    )
    provider["releases"] = [make_release(i) for i in range(1, 101)] + [
        make_release(101, "last-page.ipa", True)
    ]
    with Session(client.app.state.engine) as db:
        sync_releases(db, app["id"], client.app.state.settings)
    result = client.get(path, params={"q": "last-page", "prerelease": "only"})
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["assets"][0]["name"] == "last-page.ipa"
    assert client.get(path, params={"prerelease": "exclude"}).json()["total"] == 100
    provider["fail"] = True
    with Session(client.app.state.engine) as db:
        with pytest.raises(GitHubError):
            sync_releases(db, app["id"], client.app.state.settings)
        snapshot = db.scalar(select(GithubRepositorySync))
        assert snapshot.state == "failed"
        assert len(snapshot.releases) == 101
    assert client.get(path).json()["total"] == 101
    assert client.get(path).json()["sync_error_code"] == "GITHUB_FORBIDDEN"
    assert (
        client.delete(
            f"/api/v1/connectors/github/{connector['id']}", headers={**headers, "If-Match": '"1"'}
        ).status_code
        == 409
    )
