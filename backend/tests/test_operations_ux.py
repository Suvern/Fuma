"""Task context and grouping on an explicitly isolated PostgreSQL database."""

import base64
import os
import secrets
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_app_management_scopes import managed_apps as managed_apps

from app.core.config import Settings
from app.domains.distribution.models import TaskRecord
from app.domains.library.models import UploadRecord
from app.domains.system.models import SystemState
from app.infrastructure.database import Base, build_engine
from app.main import create_app


@pytest.fixture
def client(tmp_path, initial_password_log):
    settings = Settings(
        database_url=os.environ.get(
            "FUMA_OPERATIONS_TEST_DATABASE_URL",
            "postgresql+psycopg://fuma@127.0.0.1:55432/fuma_core_test",
        ),
        state_dir=tmp_path / "state",
        encryption_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    )
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception:
        engine.dispose()
        pytest.skip("isolated operations test database unavailable")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(SystemState(id=1))
        db.commit()
    application = create_app(settings)
    application.state.initial_password_log = initial_password_log
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client
    engine.dispose()


def test_task_context_category_search_and_cross_app_reference_guard(client, managed_apps):
    from app.domains.auth.service import utcnow

    _, apps, actor = managed_apps
    own, foreign = [UUID(app["id"]) for app in apps]
    now = utcnow()
    with Session(client.app.state.engine) as db:
        uploads = []
        for app_id, name in ((own, "release-42.ipa"), (foreign, "foreign-secret.ipa")):
            upload = UploadRecord(
                app_id=app_id,
                actor_id=actor,
                file_name=name,
                declared_size=1,
                platform="ios",
                mode="debug",
                chunk_size=1,
                expected_parts=1,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
            db.add(upload)
            db.flush()
            uploads.append(upload.id)
        tasks = [
            TaskRecord(
                app_id=own,
                kind="package_ingest",
                resource_id=str(uploads[0]),
                state="succeeded",
                created_at=now,
                updated_at=now,
            ),
            TaskRecord(
                app_id=own,
                kind="release_sync",
                payload={
                    "policy_revision": 1,
                    "result": {"release_count": 3, "asset_count": 7, "credential": "never-visible"},
                },
                state="succeeded",
                created_at=now,
                updated_at=now,
            ),
            TaskRecord(
                app_id=own, kind="cache_cleanup", state="failed", created_at=now, updated_at=now
            ),
            TaskRecord(
                app_id=foreign,
                kind="package_ingest",
                resource_id=str(uploads[1]),
                state="succeeded",
                created_at=now,
                updated_at=now,
            ),
            TaskRecord(
                app_id=own,
                kind="package_ingest",
                resource_id=str(uploads[1]),
                state="succeeded",
                created_at=now,
                updated_at=now,
            ),
        ]
        db.add_all(tasks)
        db.flush()
        ids = [task.id for task in tasks]
        db.commit()
    result = client.get("/api/v1/tasks", params={"category": "business", "page_size": 1}).json()
    assert result["total"] == 2 and len(result["items"]) == 1
    assert client.get("/api/v1/tasks", params={"category": "system"}).json()["total"] == 2
    assert client.get("/api/v1/tasks").json()["total"] == 4  # Default remains backward compatible.
    assert client.get("/api/v1/tasks", params={"category": "invalid"}).status_code == 422
    result = client.get("/api/v1/tasks", params={"q": "release-42"}).json()
    assert result["total"] == 1
    item = result["items"][0]
    assert item["app_name"] == "owned" and item["resource_name"] == "release-42.ipa"
    assert item["resource_url"] == f"/admin/apps/{own}/packages"
    assert "解析并入库" in item["result_summary"]
    assert client.get("/api/v1/tasks", params={"q": "foreign-secret"}).json()["total"] == 0
    assert client.get(f"/api/v1/tasks/{ids[3]}").status_code == 404
    corrupt = client.get(f"/api/v1/tasks/{ids[4]}").json()
    assert corrupt["resource_name"] is None and corrupt["resource_url"] is None
    sync = client.get(f"/api/v1/tasks/{ids[1]}")
    assert sync.json()["result_summary"] == "同步完成：3 个 Release、7 个附件。"
    assert "never-visible" not in sync.text


def test_task_summary_rejects_untrusted_counter_shapes():
    from types import SimpleNamespace

    from app.domains.distribution.task_presentation import result_summary

    task = SimpleNamespace(
        kind="release_import",
        state="succeeded",
        payload={
            "result": {
                "created_count": "sensitive-payload",
                "existing_count": True,
                "failed_count": -1,
            }
        },
    )
    assert "sensitive-payload" not in result_summary(task)
    task.payload = {"result": {"created_count": 2, "existing_count": 1, "failed_count": 0}}
    assert result_summary(task) == "新增 2 个、已存在 1 个、失败 0 个附件。"


def test_completed_sync_records_its_own_counts(client, managed_apps, monkeypatch):
    from app.domains.applications.models import AppRecord
    from app.domains.auth.service import utcnow
    from app.workers.tasks import execute_task

    _, apps, actor = managed_apps
    app_id = UUID(apps[0]["id"])
    now = utcnow()
    with Session(client.app.state.engine) as db:
        db.get(AppRecord, app_id).repository = {
            "connector_id": str(actor),
            "full_name": "fixture/app",
            "repository_id": "1",
        }
        task = TaskRecord(
            app_id=app_id,
            kind="release_sync",
            resource_id=str(app_id),
            created_actor_id=actor,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.flush()
        task_id = task.id
        db.commit()

    class GitHub:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def close(self):
            pass

        def get_repository(self, name):
            return {"id": 1}

        def list_releases(self, name):
            return [
                {
                    "id": 1,
                    "tag_name": "v1",
                    "draft": False,
                    "prerelease": False,
                    "body": "provider-private-note",
                    "assets": [
                        {
                            "id": 2,
                            "name": "release.ipa",
                            "size": 100,
                            "updated_at": now.isoformat(),
                        },
                    ],
                }
            ]

    monkeypatch.setattr("app.domains.github.service.get_github_client", lambda *args: GitHub())
    execute_task(client.app.state.engine, client.app.state.settings, task_id)
    result = client.get(f"/api/v1/tasks/{task_id}")
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "succeeded"
    assert result.json()["result_summary"] == "同步完成：1 个 Release、1 个附件。"
    assert "provider-private-note" not in result.text
