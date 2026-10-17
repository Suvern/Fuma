"""Archive is an explicit, revisioned operation; restore never republishes history."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app

from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord, RuleRecord, TaskRecord
from app.domains.distribution.service import enqueue
from app.domains.github.models import GithubReleasePolicy


def command(client, headers, app, action):
    return client.post(
        f"/api/v1/apps/{app['id']}/{action}",
        headers={**headers, "If-Match": f'"{app["revision"]}"'},
    )


def test_archive_restore_is_explicit_disabled_and_revisioned(client, configured_app):
    headers, app = configured_app
    assert client.get(f"/api/v1/apps/{app['id']}/archive-impact").json()["can_archive"]
    result = command(client, headers, app, "archive")
    assert result.status_code == 200, result.text
    archived = result.json()
    assert archived["archived_at"] and not archived["enabled"]
    assert client.get("/api/v1/apps?archived=true").json()["total"] == 1
    assert client.get("/api/v1/apps?archived=false").json()["total"] == 0
    assert command(client, headers, app, "restore").status_code == 412
    invalid = client.patch(
        f"/api/v1/apps/{app['id']}",
        headers={**headers, "If-Match": f'"{archived["revision"]}"'},
        json={"enabled": True},
    )
    assert invalid.status_code == 409
    restored = command(client, headers, archived, "restore").json()
    assert restored["archived_at"] is None and not restored["enabled"]
    assert restored["allowed_package_ids"] == app["allowed_package_ids"]
    assert client.get("/api/v1/audit-events?action=app.archive").json()["total"] == 1
    assert client.get("/api/v1/audit-events?action=app.restore").json()["total"] == 1


def test_archive_rechecks_all_dependencies_at_submit(client, configured_app):
    headers, app = configured_app
    assert client.get(f"/api/v1/apps/{app['id']}/archive-impact").json()["can_archive"]
    now = utcnow()
    with Session(client.app.state.engine) as db:
        db.add(
            DebugRecord(
                app_id=UUID(app["id"]),
                source_identity="f" * 64,
                connector_id=uuid4(),
                platform="android",
                file_name="old.apk",
                size_bytes=10,
                source_tag="v1",
                source={},
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            TaskRecord(
                app_id=UUID(app["id"]),
                kind="release_sync",
                state="queued",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            RuleRecord(
                app_id=UUID(app["id"]), data={"enabled": True}, created_at=now, updated_at=now
            )
        )
        db.add(GithubReleasePolicy(app_id=UUID(app["id"]), settings={}, auto_enabled=True))
        db.commit()
    impact = client.get(f"/api/v1/apps/{app['id']}/archive-impact").json()
    assert len(impact["blockers"]) == 4 and not impact["can_archive"]
    assert command(client, headers, app, "archive").status_code == 409
    with Session(client.app.state.engine) as db:
        entry = db.scalar(select(DebugRecord))
        entry.enabled = False
        db.scalar(select(TaskRecord)).state = "succeeded"
        db.scalar(select(RuleRecord)).data = {"enabled": False}
        db.get(GithubReleasePolicy, UUID(app["id"])).auto_enabled = False
        db.commit()
    archived = command(client, headers, app, "archive")
    assert archived.status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(DebugRecord)).source == {}
        with pytest.raises(AppError, match="归档"):
            enqueue(db, "release_sync", app_id=UUID(app["id"]))
        assert not db.get(AppRecord, UUID(app["id"])).enabled


def test_archive_requires_csrf_and_revision(client, configured_app):
    headers, app = configured_app
    url = f"/api/v1/apps/{app['id']}/archive"
    assert client.post(url).status_code == 403
    assert client.post(url, headers=headers).status_code == 422


def test_actions_example_matches_page_and_is_valid_yaml():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    example = (root / "deploy/github-actions-example.yml").read_text()
    assert example == (root / "frontend/src/features/m1/github-actions-example.yml").read_text()
    workflow = yaml.safe_load(example)
    step = workflow["jobs"]["debug"]["steps"][-1]
    assert step["env"]["FUMA_CI_TOKEN"] == "${{ secrets.FUMA_CI_TOKEN }}"
    assert workflow["permissions"]["contents"] == "read"
