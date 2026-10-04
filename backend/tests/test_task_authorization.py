"""Worker authority is rechecked across queueing, commits and public-copy compensation."""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_cloud_storage import cloud as cloud
from test_cloud_storage import location
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app
from test_package_library import ipa, process, send, start

from app.domains.audit.models import AuditRecord
from app.domains.auth.models import AppRoleRecord, User
from app.domains.auth.service import utcnow
from app.domains.distribution.models import TaskRecord
from app.domains.distribution.service import enqueue, state
from app.workers.tasks import execute_task


def actor_for(db, app_id):
    state(db, "feishu").data = {
        "enabled": True,
        "verified": True,
        "app_id": "worker-fixture",
        "tenant_key": "t",
    }
    user = User(
        kind="feishu",
        display_name="Worker fixture",
        open_id="worker-fixture",
        provider_app_id="worker-fixture",
        tenant_key="t",
        identity_verified_at=utcnow(),
        global_role="maintainer",
    )
    db.add(user)
    db.flush()
    db.add(AppRoleRecord(user_id=user.id, app_id=UUID(str(app_id))))
    db.commit()
    return user.id


def test_queued_work_fails_before_side_effect_after_actor_revoked(
    client, configured_app, monkeypatch
):
    _, app = configured_app
    with Session(client.app.state.engine) as db:
        actor = actor_for(db, app["id"])
        db.info.update(actor_user_id=actor, actor_permission_revision=1)
        task = enqueue(db, "release_sync", app_id=UUID(app["id"]))
        task_id = task.id
        db.get(User, actor).global_role = "downloader"
        db.commit()
    called = []
    monkeypatch.setattr("app.workers.tasks.dispatch", lambda *_: called.append(True))
    execute_task(client.app.state.engine, client.app.state.settings, task_id)
    assert not called
    with Session(client.app.state.engine) as db:
        task = db.get(TaskRecord, task_id)
        assert task.state == "failed" and task.error_code == "TASK_AUTHORIZATION_REVOKED"
        audit = db.scalar(
            select(AuditRecord).where(AuditRecord.action == "task.authorization_revoked")
        )
        assert audit.app_id == UUID(app["id"])
    response = client.get("/api/v1/audit-events", params={"action": "task.authorization_revoked"})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["outcome"] == "failure"


def test_worker_children_inherit_actor_without_requiring_browser_session(
    client, configured_app, monkeypatch
):
    _, app = configured_app
    with Session(client.app.state.engine) as db:
        actor = actor_for(db, app["id"])
        db.info.update(actor_user_id=actor, actor_permission_revision=1)
        task = enqueue(db, "release_sync", app_id=UUID(app["id"]))
        task_id = task.id
        db.commit()

    def dispatch(db, settings, parent):
        enqueue(db, "notification", app_id=parent.app_id, resource_id="child-fixture")

    monkeypatch.setattr("app.workers.tasks.dispatch", dispatch)
    execute_task(client.app.state.engine, client.app.state.settings, task_id)
    with Session(client.app.state.engine) as db:
        assert db.get(TaskRecord, task_id).state == "succeeded"
        child = db.scalar(select(TaskRecord).where(TaskRecord.resource_id == "child-fixture"))
        assert child.created_actor_id == actor and child.actor_permission_revision == 1


@pytest.mark.parametrize("revoke_during_publish", [True, False])
def test_publication_revocation_compensates_but_committed_reclaim_continues(
    client, configured_app, cloud, monkeypatch, revoke_during_publish
):
    headers, app = configured_app
    public = location(client, headers, "public")
    data = ipa()
    upload = start(client, headers, app, data, monkeypatch)
    send(client, headers, upload, data)
    client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers)
    package = process(client, upload)
    version = client.post(
        f"/api/v1/apps/{app['id']}/versions",
        headers=headers,
        json={"display_name": "authority", "mode": "release", "release_notes": "fixture"},
    ).json()
    publication = client.post(
        f"/api/v1/versions/{version['id']}/publications",
        headers=headers,
        json={"platform": "ios", "package_ids": [package], "public_storage_id": public["id"]},
    ).json()
    pid = publication["id"]
    result = client.post(
        f"/api/v1/publications/{pid}/publish", headers={**headers, "If-Match": '"1"'}
    ).json()
    task_id = UUID(result["access_task_id"])
    with Session(client.app.state.engine) as db:
        actor = actor_for(db, app["id"])
        db.get(TaskRecord, task_id).created_actor_id = actor
        db.commit()
    original = cloud.put
    revoked = False

    def put(key, path, sha256, public=False):
        nonlocal revoked
        original(key, path, sha256, public=public)
        # A separate transaction can revoke even while provider I/O is in flight.
        # The already-started put is compensated before the final publish fence.
        if revoke_during_publish and public and not revoked:
            with Session(client.app.state.engine) as other:
                other.get(User, actor).global_role = "downloader"
                other.commit()
            revoked = True

    monkeypatch.setattr(cloud, "put", put)
    execute_task(client.app.state.engine, client.app.state.settings, task_id)
    row = client.get(f"/api/v1/publications/{pid}").json()
    if revoke_during_publish:
        assert revoked and row["access_state"] == "publish_failed"
        assert row["state"] != "published" and not cloud.files
        assert client.get(f"/api/v1/catalog/publications/{pid}").status_code in {403, 404}
    else:
        assert row["state"] == "published" and cloud.files
        result = client.post(
            f"/api/v1/publications/{pid}/unpublish",
            headers={**headers, "If-Match": f'"{row["revision"]}"'},
        ).json()
        with Session(client.app.state.engine) as db:
            db.get(TaskRecord, UUID(result["access_task_id"])).created_actor_id = actor
            db.get(User, actor).global_role = "downloader"
            db.commit()
        execute_task(client.app.state.engine, client.app.state.settings, result["access_task_id"])
        row = client.get(f"/api/v1/publications/{pid}").json()
        assert row["access_state"] == "reclaimed" and not cloud.files
