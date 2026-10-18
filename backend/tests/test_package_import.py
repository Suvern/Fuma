from contextlib import nullcontext
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_cloud_storage import cloud as cloud
from test_cloud_storage import location
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app
from test_m2_applications import ensure_ready_binding
from test_package_library import ipa, process, send

from app.domains.applications.models import AppRecord
from app.domains.github.models import GithubRepositorySync
from app.domains.library.models import PackageRecord, PublicationRecord


@pytest.fixture
def source(client, configured_app, monkeypatch, storage_cloud):
    headers, app = configured_app
    ensure_ready_binding(client, app["id"], "debug")
    ensure_ready_binding(client, app["id"], "release")
    content = ipa()
    binding = {"connector_id": str(uuid4()), "repository_id": "90", "full_name": "example/mobile"}
    asset = {
        "id": "80",
        "name": "mobile.ipa",
        "size_bytes": len(content),
        "updated_at": "2026-10-04T00:00:00Z",
        "digest": None,
        "supported": True,
        "platform": "ios",
    }
    release = {"id": "70", "draft": False, "tag_name": "v1", "assets": [asset]}
    with Session(client.app.state.engine) as db:
        row = db.get(AppRecord, UUID(app["id"]))
        row.repository = binding
        db.add(
            GithubRepositorySync(
                app_id=row.id, repository_id="90", state="ready", releases=[release]
            )
        )
        db.commit()

    class GitHub:
        changed = False

        def get_repository(self, _):
            return {"id": 90}

        def get_release(self, *_):
            return {
                "draft": False,
                "assets": [
                    {
                        "id": 80,
                        "name": "changed.ipa" if self.changed else "mobile.ipa",
                        "size": len(content),
                        "updated_at": asset["updated_at"],
                        "digest": None,
                    }
                ],
            }

        def download_asset(self, _full, _asset, path, _size):
            path.write_bytes(content)

    fake = GitHub()
    monkeypatch.setattr(
        "app.domains.library.github_import.get_github_client", lambda *_: nullcontext(fake)
    )
    return headers, app, content, fake


def test_import_replay_and_draft_link_use_common_parser(client, source):
    headers, app, _, _ = source
    version = client.post(
        f"/api/v1/apps/{app['id']}/versions",
        headers=headers,
        json={"display_name": "导入版本", "mode": "release", "release_notes": ""},
    ).json()
    body = {"release_id": "70", "asset_id": "80", "mode": "release", "version_id": version["id"]}
    result = client.post(f"/api/v1/apps/{app['id']}/package-imports", headers=headers, json=body)
    assert result.status_code == 202, result.text
    upload = result.json()
    assert (
        client.post(f"/api/v1/apps/{app['id']}/package-imports", headers=headers, json=body).json()[
            "id"
        ]
        == upload["id"]
    )
    package_id = process(client, upload)
    with Session(client.app.state.engine) as db:
        package = db.get(PackageRecord, UUID(package_id))
        assert package.source_kind == "github" and package.package_identifier == "com.example.app"
        publication = db.scalar(select(PublicationRecord))
        assert publication.state == "draft" and publication.version_id == UUID(version["id"])
    assert (
        client.post(
            f"/api/v1/apps/{app['id']}/package-imports",
            headers=headers,
            json={**body, "mode": "debug"},
        ).status_code
        == 409
    )


def test_changed_source_never_reaches_parser_or_ready_package(client, source):
    headers, app, _, fake = source
    result = client.post(
        f"/api/v1/apps/{app['id']}/package-imports",
        headers=headers,
        json={"release_id": "70", "asset_id": "80", "mode": "release"},
    )
    assert result.status_code == 202, result.text
    fake.changed = True
    from app.workers.tasks import execute_task

    execute_task(client.app.state.engine, client.app.state.settings, result.json()["task_id"])
    upload = client.get(f"/api/v1/uploads/{result.json()['id']}").json()
    assert upload["state"] == "failed"
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(PackageRecord)) is None


@pytest.mark.parametrize("fail_first", [False, True])
def test_legacy_migration_upgrades_deduplicated_local_package_atomically(
    client, source, cloud, fail_first, monkeypatch
):
    import hashlib

    from app.core.errors import AppError
    from app.domains.applications.models import AllowedPackageIdRecord
    from app.domains.auth.service import utcnow
    from app.domains.distribution.models import DebugRecord, TaskRecord
    from app.domains.library.ingestion import ingest
    from app.domains.library.models import UploadRecord
    from app.domains.storage.service import canonical

    headers, app, content, _ = source
    with Session(client.app.state.engine) as db:
        db.add(
            AllowedPackageIdRecord(
                app_id=UUID(app["id"]),
                platform="ios",
                mode="debug",
                identifier="com.example.app",
                normalized_identifier="com.example.app",
            )
        )
        db.commit()
    result = client.post(
        f"/api/v1/apps/{app['id']}/uploads",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json=dict(file_name="mobile.ipa", declared_size=len(content), platform="ios", mode="debug"),
    )
    assert result.status_code == 201, result.text
    local_upload = result.json()
    send(client, headers, local_upload, content)
    client.post(f"/api/v1/uploads/{local_upload['id']}/complete", headers=headers)
    package_id = UUID(process(client, local_upload))
    current_bindings = client.get(f"/api/v1/apps/{app['id']}/package-storage").json()
    target = location(client, headers)
    current_app = app
    rebound = client.put(
        f"/api/v1/apps/{app['id']}/package-storage",
        headers={**headers, "If-Match": f'"{current_app["revision"]}"'},
        json={
            "debug": {"storage_location_id": target["id"], "object_prefix": "debug"},
            "release": {
                "storage_location_id": current_bindings["release"]["storage_location_id"],
                "object_prefix": "release",
            },
        },
    )
    assert rebound.status_code == 200, rebound.text
    with Session(client.app.state.engine) as db:
        binding = db.get(AppRecord, UUID(app["id"])).repository
        legacy = DebugRecord(
            app_id=UUID(app["id"]),
            connector_id=UUID(binding["connector_id"]),
            source_identity="a" * 64,
            platform="ios",
            file_name="mobile.ipa",
            size_bytes=len(content),
            source_tag="v1",
            source={
                "repository_id": "90",
                "release_id": "70",
                "asset_id": "80",
                "asset_updated_at": "2026-10-04T00:00:00Z",
                "digest": None,
            },
            sha256=hashlib.sha256(content).hexdigest(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id
    result = client.post(
        f"/api/v1/debug-entries/{legacy_id}/persist",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"storage_location_id": target["id"]},
    )
    assert result.status_code == 202, result.text
    migration = result.json()
    monkeypatch.setattr("app.domains.storage.service.adapter", lambda *_: cloud)
    if fail_first:
        cloud.fail_upload = True
        with pytest.raises(AppError):
            process(client, migration, keep_cloud=True)
        with Session(client.app.state.engine) as db:
            assert db.get(PackageRecord, package_id).storage_location_id is None
            assert db.get(PackageRecord, package_id).state == "ready"
            assert db.get(DebugRecord, legacy_id).persistent_package_id is None
        cloud.fail_upload = False
        with Session(client.app.state.engine) as db:
            task = db.get(TaskRecord, UUID(migration["task_id"]))
            ingest(db, client.app.state.settings, task)
    else:
        assert UUID(process(client, migration, keep_cloud=True)) == package_id
    with Session(client.app.state.engine) as db:
        package = db.get(PackageRecord, package_id)
        assert package.storage_location_id == UUID(target["id"])
        assert db.get(DebugRecord, legacy_id).persistent_package_id == package_id
        assert db.get(UploadRecord, UUID(migration["id"])).state == "ready"
        assert canonical(db, package).location_id == UUID(target["id"])


def test_deleted_package_can_be_restored_by_verified_reimport(client, source):
    from datetime import timedelta

    from app.domains.auth.service import utcnow
    from app.workers.tasks import execute_task

    headers, app, _, _ = source
    body = {"release_id": "70", "asset_id": "80", "mode": "release"}
    first = client.post(
        f"/api/v1/apps/{app['id']}/package-imports", headers=headers, json=body
    ).json()
    package_id = UUID(process(client, first))
    with Session(client.app.state.engine) as db:
        package = db.get(PackageRecord, package_id)
        package.created_at = utcnow() - timedelta(hours=25)
        revision = package.revision
        db.commit()
    result = client.delete(
        f"/api/v1/packages/{package_id}", headers={**headers, "If-Match": f'"{revision}"'}
    )
    assert result.status_code == 202, result.text
    execute_task(client.app.state.engine, client.app.state.settings, result.json()["task_id"])
    assert client.get(f"/api/v1/packages/{package_id}").json()["state"] == "deleted"
    repeated = client.post(
        f"/api/v1/apps/{app['id']}/package-imports",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert repeated.status_code == 202, repeated.text
    assert UUID(process(client, repeated.json())) == package_id
    with Session(client.app.state.engine) as db:
        restored = db.get(PackageRecord, package_id)
        assert restored.state == "ready" and restored.revision > revision
        assert restored.created_at > utcnow() - timedelta(minutes=1)


def test_parser_cleanup_failure_does_not_revert_successful_ingestion(client, source, monkeypatch):
    from pathlib import Path

    from app.domains.library.models import UploadRecord
    from app.workers.tasks import execute_task

    headers, app, _, _ = source
    result = client.post(
        f"/api/v1/apps/{app['id']}/package-imports",
        headers=headers,
        json={"release_id": "70", "asset_id": "80", "mode": "release"},
    )
    assert result.status_code == 202, result.text
    upload = result.json()
    original = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.parent == client.app.state.settings.parser_outbox and path.suffix == ".json":
            raise PermissionError("fixture cleanup denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    process(client, upload)
    # A task redelivery must see ready and succeed despite the leftover parser file.
    execute_task(client.app.state.engine, client.app.state.settings, upload["task_id"])
    with Session(client.app.state.engine) as db:
        assert db.get(UploadRecord, UUID(upload["id"])).state == "ready"
    task = client.get(f"/api/v1/tasks/{upload['task_id']}").json()
    assert task["state"] == "succeeded"
