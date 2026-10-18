from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app
from test_package_library import ipa, process, send, start

from app.domains.auth.service import utcnow
from app.domains.library.models import PackageRecord, UploadRecord
from app.workers.tasks import execute_task


def package(client, configured_app, monkeypatch):
    headers, app = configured_app
    content = ipa()
    upload = start(client, headers, app, content, monkeypatch)
    send(client, headers, upload, content)
    client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers)
    return headers, app, process(client, upload)


def test_default_is_explicit_revisioned_and_cleared_on_unpublish(
    client, configured_app, storage_cloud, monkeypatch
):
    headers, app, pid = package(client, configured_app, monkeypatch)
    version = client.post(
        f"/api/v1/apps/{app['id']}/versions",
        headers=headers,
        json={"display_name": "default", "mode": "release", "release_notes": ""},
    ).json()
    publication = client.post(
        f"/api/v1/versions/{version['id']}/publications",
        headers=headers,
        json={"platform": "ios", "package_ids": [pid]},
    ).json()
    path = f"/api/v1/apps/{app['id']}/release-defaults/ios"
    assert client.get(path).json()["publication_id"] is None
    assert (
        client.put(
            path, headers={**headers, "If-Match": '"0"'}, json={"publication_id": publication["id"]}
        ).status_code
        == 409
    )
    client.post(
        f"/api/v1/publications/{publication['id']}/publish", headers={**headers, "If-Match": '"1"'}
    )
    result = client.put(
        path, headers={**headers, "If-Match": '"0"'}, json={"publication_id": publication["id"]}
    )
    assert result.status_code == 200, result.text
    assert (
        client.put(
            path, headers={**headers, "If-Match": '"0"'}, json={"publication_id": None}
        ).status_code
        == 412
    )
    client.post(
        f"/api/v1/publications/{publication['id']}/unpublish",
        headers={**headers, "If-Match": '"2"'},
    )
    assert client.get(path).json()["publication_id"] is None
    assert any(
        "引用" in b
        for b in client.get(f"/api/v1/packages/{pid}/deletion-impact").json()["blockers"]
    )


def test_deletion_retention_and_expired_upload_cleanup(
    client, configured_app, storage_cloud, monkeypatch
):
    headers, app, pid = package(client, configured_app, monkeypatch)
    result = client.delete(f"/api/v1/packages/{pid}", headers={**headers, "If-Match": '"1"'})
    assert result.status_code == 409
    with Session(client.app.state.engine) as db:
        p = db.get(PackageRecord, UUID(pid))
        p.created_at = utcnow() - timedelta(days=2)
        db.commit()
    result = client.delete(f"/api/v1/packages/{pid}", headers={**headers, "If-Match": '"1"'})
    assert result.status_code == 202, result.text
    execute_task(client.app.state.engine, client.app.state.settings, result.json()["task_id"])
    assert client.get(f"/api/v1/packages/{pid}").json()["state"] == "deleted"
    from app.api.library import upload_dir
    from app.domains.library.cleanup import cleanup_expired

    upload = start(client, headers, app, ipa(build="43"), monkeypatch)
    directory = upload_dir(client.app.state.settings, upload["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "1").write_bytes(b"partial")
    with Session(client.app.state.engine) as db:
        row = db.get(UploadRecord, UUID(upload["id"]))
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        cleanup_expired(db, client.app.state.settings)
    assert not directory.exists()
    assert client.get(f"/api/v1/uploads/{upload['id']}").json()["state"] == "expired"
