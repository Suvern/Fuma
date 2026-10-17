"""M2 App configuration against disposable PostgreSQL; never reads local dotenv."""

import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import complete_first_login
from test_core_auth_apps import core_app as core_app

from app.domains.applications.models import AllowedPackageIdRecord, AppCreation
from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord, TaskRecord
from app.domains.storage.models import StorageLocation


def identifier(platform="android", mode="debug", value="com.example.app"):
    return {"platform": platform, "mode": mode, "identifier": value}


@pytest.fixture
def configured_app(client):
    headers = {**complete_first_login(client), "Idempotency-Key": str(uuid4())}
    body = {
        "name": "M2 应用",
        "public_slug": "m2-app",
        "platforms": ["android", "ios"],
        "allowed_package_ids": [identifier(), identifier("ios", "release", "com.Example.App")],
    }
    response = client.post("/api/v1/apps", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return headers, response.json()


def patch(client, headers, app, body):
    return client.patch(
        f"/api/v1/apps/{app['id']}",
        headers={**headers, "If-Match": f'"{app["revision"]}"'},
        json=body,
    )


def test_package_ids_scope_deduplication_and_idempotency(client):
    headers = {**complete_first_login(client), "Idempotency-Key": str(uuid4())}
    items = [
        identifier(),
        identifier(),
        identifier(value="com.Example.app"),
        identifier(mode="release"),
        identifier("ios", "debug", "Com.Example.App"),
        identifier("ios", "debug", "com.example.app"),
    ]
    body = {
        "name": "标识配置",
        "public_slug": "identifiers",
        "platforms": ["android", "ios"],
        "allowed_package_ids": items,
    }
    first = client.post("/api/v1/apps", headers=headers, json=body)
    assert first.status_code == 201, first.text
    stored = first.json()["allowed_package_ids"]
    assert len(stored) == 4
    assert identifier("ios", "debug", "Com.Example.App") in stored
    assert identifier(value="com.Example.app") in stored
    replay = client.post("/api/v1/apps", headers=headers, json=body)
    assert replay.json() == first.json()
    assert client.get("/api/v1/audit-events?action=app.create").json()["total"] == 1


def test_package_storage_binding_isolated_prefixes_and_revision(client, configured_app):
    headers, app = configured_app
    storage_id = uuid4()
    with Session(client.app.state.engine) as db:
        db.add(
            StorageLocation(
                id=storage_id,
                name="测试包存储",
                provider="oss",
                region="cn-hangzhou",
                bucket="fuma-test",
                prefix="fuma/test",
                read_mode="private",
                encrypted_credentials="{}",
                enabled=True,
                is_default=False,
                status="ready",
                revision=1,
                capabilities={},
            )
        )
        db.commit()

    get_result = client.get(f"/api/v1/apps/{app['id']}/package-storage", headers=headers)
    assert get_result.status_code == 200, get_result.text
    assert get_result.json()["debug"] is None

    second_storage_id = uuid4()
    with Session(client.app.state.engine) as db:
        db.add(
            StorageLocation(
                id=second_storage_id,
                name="测试 Release 存储",
                provider="oss",
                region="cn-shanghai",
                bucket="fuma-release-test",
                prefix="fuma/release",
                read_mode="private",
                encrypted_credentials="{}",
                enabled=True,
                is_default=False,
                status="ready",
                revision=1,
                capabilities={},
            )
        )
        db.commit()

    saved = client.put(
        f"/api/v1/apps/{app['id']}/package-storage",
        headers={**headers, "If-Match": f'"{app["revision"]}"'},
        json={
            "debug": {"storage_location_id": str(storage_id), "object_prefix": "debug"},
            "release": {"storage_location_id": str(second_storage_id), "object_prefix": "release"},
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["debug"]["object_prefix"] == "debug"
    assert saved.json()["app_revision"] == app["revision"] + 1

    conflict = client.put(
        f"/api/v1/apps/{app['id']}/package-storage",
        headers={**headers, "If-Match": f'"{saved.json()["app_revision"]}"'},
        json={
            "debug": {"storage_location_id": str(storage_id), "object_prefix": "packages"},
            "release": {
                "storage_location_id": str(storage_id),
                "object_prefix": "packages/release",
            },
        },
    )
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "STORAGE_BUCKET_CONFLICT"

    invalid = client.put(
        f"/api/v1/apps/{app['id']}/package-storage",
        headers={**headers, "If-Match": f'"{saved.json()["app_revision"]}"'},
        json={
            "debug": {"storage_location_id": str(storage_id), "object_prefix": "../debug"},
            "release": None,
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_STORAGE_PREFIX"

    cleared = client.put(
        f"/api/v1/apps/{app['id']}/package-storage",
        headers={**headers, "If-Match": f'"{saved.json()["app_revision"]}"'},
        json={"debug": None, "release": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["debug"] is None and cleared.json()["release"] is None


def test_legacy_create_request_hash_and_explicit_null(client):
    headers = {**complete_first_login(client), "Idempotency-Key": str(uuid4())}
    body = {"name": "M1 App", "public_slug": "legacy", "platforms": ["android"]}
    result = client.post("/api/v1/apps", headers=headers, json=body)
    assert result.status_code == 201
    with Session(client.app.state.engine) as db:
        record = db.scalar(select(AppCreation))
        legacy_hash = hashlib.sha256(
            json.dumps({**body, "description": None}, sort_keys=True).encode()
        ).hexdigest()
        assert record.body_hash == legacy_hash
    assert client.post("/api/v1/apps", headers=headers, json=body).json() == result.json()
    result = client.post(
        "/api/v1/apps",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**body, "public_slug": "invalid", "allowed_package_ids": None},
    )
    assert result.status_code == 422


@pytest.mark.parametrize(
    "items",
    [
        [identifier(value="com.1example.app")],
        [identifier(value="com.example.*")],
        [identifier(value="com.example-app")],
        [identifier(value="app")],
        [identifier("ios", value="com.example_app")],
        [identifier("ios", value="com..example")],
        [identifier(value=" com.example.app")],
        [identifier(value="a" * 256)],
        [identifier(mode="other")],
        [identifier("harmonyos")],
        [identifier()] * 81,
        None,
    ],
)
def test_invalid_configuration_is_atomic(client, configured_app, items):
    headers, app = configured_app
    response = patch(client, headers, app, {"name": "不应保存", "allowed_package_ids": items})
    assert response.status_code == 422, response.text
    assert client.get(f"/api/v1/apps/{app['id']}").json() == app


def test_configuration_omission_clear_and_revision(client, configured_app):
    headers, app = configured_app
    renamed = patch(client, headers, app, {"name": "新名称"}).json()
    assert renamed["allowed_package_ids"] == app["allowed_package_ids"]
    assert patch(client, headers, app, {"allowed_package_ids": []}).status_code == 412
    cleared = patch(client, headers, renamed, {"allowed_package_ids": []})
    assert cleared.status_code == 200
    assert cleared.json()["allowed_package_ids"] == []
    assert cleared.json()["revision"] == 3


def test_platform_removal_clears_only_removed_configuration(client, configured_app):
    headers, app = configured_app
    result = patch(client, headers, app, {"platforms": ["android"]})
    assert result.status_code == 200, result.text
    app = result.json()
    assert app["allowed_package_ids"] == [identifier()]
    result = patch(client, headers, app, {"allowed_package_ids": [identifier("ios")]})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "PACKAGE_PLATFORM_DISABLED"
    # Owned configuration must not prevent the legacy delete of an otherwise empty App.
    result = client.delete(
        f"/api/v1/apps/{app['id']}",
        headers={**headers, "If-Match": '"2"'},
    )
    assert result.status_code == 204
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(AllowedPackageIdRecord)) is None


def test_existing_disabled_package_blocks_platform_removal(client, configured_app):
    headers, app = configured_app
    now = utcnow()
    with Session(client.app.state.engine) as db:
        db.add(
            DebugRecord(
                app_id=UUID(app["id"]),
                source_identity="a" * 64,
                connector_id=uuid4(),
                enabled=False,
                platform="ios",
                file_name="old.ipa",
                size_bytes=10,
                source_tag="v1",
                source={"legacy": True},
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    result = patch(client, headers, app, {"platforms": ["android"]})
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "PLATFORM_IN_USE"
    assert "old.ipa" in result.json()["error"]["message"]
    assert client.get(f"/api/v1/apps/{app['id']}").json()["platforms"] == ["android", "ios"]
    # Changing future policy never rewrites the source or metadata of an M1 entry.
    assert patch(client, headers, app, {"allowed_package_ids": []}).status_code == 200
    with Session(client.app.state.engine) as db:
        entry = db.scalar(select(DebugRecord))
        assert entry.source == {"legacy": True}
        assert entry.version_name is None and entry.sha256 is None


def test_pending_task_blocks_platform_removal(client, configured_app):
    headers, app = configured_app
    now = utcnow()
    with Session(client.app.state.engine) as db:
        task = TaskRecord(
            app_id=UUID(app["id"]),
            kind="release_import",
            state="queued",
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.commit()
        task_id = task.id
    assert patch(client, headers, app, {"platforms": ["ios"]}).status_code == 409
    with Session(client.app.state.engine) as db:
        db.get(TaskRecord, task_id).state = "succeeded"
        db.commit()
    assert patch(client, headers, app, {"platforms": ["ios"]}).status_code == 200


def test_combined_filters_literal_search_and_ordering(client, configured_app):
    headers, app = configured_app
    second = client.post(
        "/api/v1/apps",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"name": "Other", "public_slug": "other", "platforms": ["ios"]},
    ).json()
    assert second["allowed_package_ids"] == []
    patch(client, headers, second, {"enabled": False})
    result = client.get(
        "/api/v1/apps",
        params={
            "q": "COM.EXAMPLE",
            "platform": "android",
            "enabled": True,
            "page_size": 1,
        },
    ).json()
    assert result["total"] == 1 and result["items"][0]["id"] == app["id"]
    assert client.get("/api/v1/apps?enabled=false&platform=ios").json()["total"] == 1
    assert client.get("/api/v1/apps?q=%25").json()["total"] == 0
    assert client.get("/api/v1/apps?q=_").json()["total"] == 0
    assert client.get("/api/v1/apps?platform=harmonyos").status_code == 422
    assert client.get("/api/v1/apps?enabled=garbage").status_code == 422
    assert client.get("/api/v1/apps").json()["items"][0]["id"] == app["id"]


def test_m2_migration_preserves_m1_application(core_app):
    directory = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    schema = "m2_migration_" + uuid4().hex
    app_id = uuid4()
    with core_app.state.test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with Operations.context(MigrationContext.configure(connection)):
            for path in sorted(directory.glob("000[1-7]*.py")):
                spec = importlib.util.spec_from_file_location(path.stem, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
            connection.execute(
                text(
                    "INSERT INTO applications (id,name,public_slug,description,platforms,enabled,"
                    "revision,created_at,updated_at) VALUES "
                    "(:id,'Legacy','legacy','', '[\"android\"]',true,3,now(),now())"
                ),
                {"id": app_id},
            )
            before = connection.execute(text("SELECT * FROM applications")).one()
            path = directory / "0008_app_package_ids.py"
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade()
            assert connection.execute(text("SELECT * FROM applications")).one() == before
            count = connection.execute(text("SELECT count(*) FROM allowed_package_ids")).scalar()
            assert count == 0
            module.downgrade()
            assert connection.execute(text("SELECT * FROM applications")).one() == before
            module.upgrade()
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
