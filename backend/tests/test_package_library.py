"""Real PostgreSQL upload/publish flow with bounded offline parsing of synthetic IPA fixtures."""

import hashlib
import importlib.util
import io
import plistlib
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app

from app.core.errors import AppError
from app.domains.distribution.models import TaskRecord
from app.domains.distribution.service import RetryLater
from app.domains.library.ingestion import ingest
from app.domains.library.models import PackageRecord, UploadRecord
from app.domains.storage.models import StorageLocation

ROOT = Path(__file__).resolve().parents[2]


def ipa(identifier="com.example.app", build="42"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr(
            "Payload/Demo.app/Info.plist",
            plistlib.dumps(
                dict(
                    CFBundleIdentifier=identifier,
                    CFBundleShortVersionString="1.0",
                    CFBundleVersion=build,
                    MinimumOSVersion="15.0",
                )
            ),
        )
    return output.getvalue()


def parser_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "parser" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def start(client, headers, app, data, monkeypatch):
    monkeypatch.setattr("app.api.library.CHUNK_SIZE", 128)
    result = client.post(
        f"/api/v1/apps/{app['id']}/uploads",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json=dict(file_name="demo.ipa", declared_size=len(data), platform="ios", mode="release"),
    )
    assert result.status_code == 201, result.text
    return result.json()


def send(client, headers, upload, data):
    for i in range(upload["expected_parts"], 0, -1):
        piece = data[(i - 1) * upload["chunk_size"] : i * upload["chunk_size"]]
        result = client.put(
            f"/api/v1/uploads/{upload['id']}/parts/{i}",
            headers={
                **headers,
                "X-Chunk-SHA256": hashlib.sha256(piece).hexdigest(),
                "Content-Type": "application/octet-stream",
            },
            content=piece,
        )
        assert result.status_code == 200, result.text


def process(client, upload):
    settings = client.app.state.settings
    with Session(client.app.state.engine) as db:
        row = db.get(UploadRecord, UUID(upload["id"]))
        task = db.get(TaskRecord, row.task_id)
        with pytest.raises(RetryLater):
            ingest(db, settings, task)
        parser_module("service").process(
            settings.parser_inbox / f"{task.id}.json", settings.parser_outbox
        )
        ingest(db, settings, task)
        return str(db.get(UploadRecord, row.id).package_id)


def test_resumable_chunks_hash_conflicts_and_cancel(client, configured_app, monkeypatch):
    headers, app = configured_app
    data = ipa()
    upload = start(client, headers, app, data, monkeypatch)
    assert (
        client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers).status_code == 409
    )
    send(client, headers, upload, data)
    send(client, headers, upload, data)  # Exact retries are idempotent and may arrive out of order.
    current = client.get(f"/api/v1/uploads/{upload['id']}").json()
    assert len(current["parts"]) == upload["expected_parts"]
    different = b"x" * 128
    result = client.put(
        f"/api/v1/uploads/{upload['id']}/parts/1",
        headers={**headers, "X-Chunk-SHA256": hashlib.sha256(different).hexdigest()},
        content=different,
    )
    assert result.status_code == 409
    assert (
        client.delete(f"/api/v1/uploads/{upload['id']}", headers=headers).json()["state"]
        == "cancelled"
    )
    assert (
        client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers).status_code == 409
    )


def test_upload_uses_app_channel_storage_binding_when_not_explicit(
    client, configured_app, monkeypatch
):
    headers, app = configured_app
    storage_id = uuid4()
    with Session(client.app.state.engine) as db:
        db.add(
            StorageLocation(
                id=storage_id,
                name="Release 原件存储",
                provider="oss",
                region="cn-hangzhou",
                bucket="fuma-test",
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
    bound = client.put(
        f"/api/v1/apps/{app['id']}/package-storage",
        headers={**headers, "If-Match": f'"{app["revision"]}"'},
        json={
            "debug": None,
            "release": {"storage_location_id": str(storage_id), "object_prefix": "release"},
        },
    )
    assert bound.status_code == 200, bound.text
    upload = start(client, headers, app, ipa(), monkeypatch)
    assert upload["storage_location_id"] == str(storage_id)


def test_upload_parse_publish_download_unpublish_and_restore(client, configured_app, monkeypatch):
    headers, app = configured_app
    data = ipa()
    upload = start(client, headers, app, data, monkeypatch)
    send(client, headers, upload, data)
    accepted = client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers)
    assert accepted.status_code == 202
    assert (
        client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers).json()["task_id"]
        == accepted.json()["task_id"]
    )
    package_id = process(client, upload)
    package = client.get(f"/api/v1/packages/{package_id}").json()
    assert package["package_identifier"] == "com.example.app" and package["build_number"] == "42"
    assert package["sha256"] == hashlib.sha256(data).hexdigest()
    assert "未验证" in package["signature_status"]
    version = client.post(
        f"/api/v1/apps/{app['id']}/versions",
        headers=headers,
        json=dict(display_name="版本 1", mode="release", release_notes="发布说明"),
    ).json()
    response = client.post(
        f"/api/v1/versions/{version['id']}/publications",
        headers=headers,
        json=dict(platform="ios", package_ids=[package_id]),
    )
    assert response.status_code == 201, response.text
    publication = response.json()
    pid = publication["id"]
    assert (
        client.get(f"/api/v1/catalog/publications/{pid}").status_code == 404
    )  # Authenticated administrators still cannot download unpublished drafts.
    published = client.post(
        f"/api/v1/publications/{pid}/publish", headers={**headers, "If-Match": '"1"'}
    )
    assert published.status_code == 200, published.text
    assert published.json()["file_set_frozen"]
    assert (
        client.post(
            f"/api/v1/publications/{pid}/unpublish", headers={**headers, "If-Match": '"1"'}
        ).status_code
        == 412
    )
    catalog = client.get(f"/api/v1/catalog/publications/{pid}").json()
    assert catalog["files"][0]["sha256"] == package["sha256"]
    assert "internal_notes" not in catalog["files"][0]
    grant = client.post(
        f"/api/v1/catalog/publications/{pid}/grants",
        headers=headers,
        json={"package_id": package_id},
    )
    assert grant.status_code == 200, grant.text
    url = grant.json()["url"]
    assert client.get(url).content == data
    head = client.head(url)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(data))
    partial = client.get(url, headers={"Range": "bytes=0-15"})
    assert partial.status_code == 206 and partial.content == data[:16]
    totals = client.get(f"/api/v1/apps/{app['id']}/distribution-statistics").json()["totals"]
    assert totals["grant_count"] == 1
    assert totals["local_get_requests"] == 2 and totals["local_head_requests"] == 1
    assert totals["observed_bytes"] == len(data) + 16
    result = client.post(
        f"/api/v1/publications/{pid}/unpublish", headers={**headers, "If-Match": '"2"'}
    )
    assert result.status_code == 200
    assert client.get(f"/api/v1/catalog/publications/{pid}").status_code == 404
    assert (
        client.post(
            f"/api/v1/catalog/publications/{pid}/grants",
            headers=headers,
            json={"package_id": package_id},
        ).status_code
        == 404
    )
    assert (
        client.get(url).content == data
    )  # Existing five-minute capability intentionally remains valid.
    archived = client.post(
        f"/api/v1/publications/{pid}/archive", headers={**headers, "If-Match": '"3"'}
    )
    assert archived.status_code == 200
    restored = client.post(
        f"/api/v1/publications/{pid}/restore", headers={**headers, "If-Match": '"4"'}
    ).json()
    assert restored["state"] == "draft" and restored["file_set_frozen"]
    client.app.dependency_overrides.clear()


def test_parser_identity_mismatch_never_creates_ready_package(client, configured_app, monkeypatch):
    headers, app = configured_app
    data = ipa("com.other.app")
    upload = start(client, headers, app, data, monkeypatch)
    send(client, headers, upload, data)
    client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers)
    settings = client.app.state.settings
    with Session(client.app.state.engine) as db:
        row = db.get(UploadRecord, UUID(upload["id"]))
        task = db.get(TaskRecord, row.task_id)
        with pytest.raises(RetryLater):
            ingest(db, settings, task)
        parser_module("service").process(
            settings.parser_inbox / f"{task.id}.json", settings.parser_outbox
        )
        with pytest.raises(AppError) as raised:
            ingest(db, settings, task)
        assert raised.value.code == "PACKAGE_ID_MISMATCH"
        assert db.scalar(select(PackageRecord)) is None


@pytest.mark.parametrize("name", ["../escape", "/absolute", "Payload/Demo.app/../../escape"])
def test_parser_rejects_unsafe_zip_entries(tmp_path, name):
    package = tmp_path / "file.ipa"
    with zipfile.ZipFile(package, "w") as z:
        z.writestr(name, "unsafe")
    with pytest.raises(ValueError):
        parser_module("parse_package").parse(package, "ios")


def test_version_and_publication_create_retries_are_idempotent(client, configured_app, monkeypatch):
    headers, app = configured_app
    upload = start(client, headers, app, ipa(), monkeypatch)
    send(client, headers, upload, ipa())
    client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers)
    package_id = process(client, upload)
    headers = {**headers, "Idempotency-Key": str(uuid4())}
    path = f"/api/v1/apps/{app['id']}/versions"
    body = dict(display_name="同一创建意图", mode="release", release_notes="")
    version = client.post(path, headers=headers, json=body)
    assert version.status_code == 201
    assert client.post(path, headers=headers, json=body).json()["id"] == version.json()["id"]
    assert (
        client.post(path, headers=headers, json={**body, "display_name": "不同内容"}).status_code
        == 409
    )
    path = f"/api/v1/versions/{version.json()['id']}/publications"
    body = dict(platform="ios", package_ids=[package_id])
    publication = client.post(path, headers=headers, json=body)
    assert publication.status_code == 201
    assert client.post(path, headers=headers, json=body).json()["id"] == publication.json()["id"]
