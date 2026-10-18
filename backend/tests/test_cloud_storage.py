"""Cloud failure/compensation boundaries use deterministic provider doubles, never live buckets."""

import hashlib
import json
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app
from test_package_library import ipa, process, send, start

from app.core.errors import AppError
from app.domains.storage.adapter import Adapter
from app.domains.storage.cos_ingestion import _archive_manifest
from app.domains.storage.models import StorageLocation, StoredObject
from app.workers.tasks import execute_task


class FakeCloud:
    def __init__(self):
        self.files = {}
        self.fail_delete = False
        self.fail_upload = False

    def check_bucket(self):
        pass

    def put(self, key, path, sha256, public=False):
        if self.fail_upload:
            raise AppError(503, "STORAGE_UPLOAD_FAILED", "测试上传失败")
        self.files[key] = (Path(path).read_bytes(), sha256, public)

    def verify(self, key, size, sha256, public=False, full=False):
        data, sha, accessible = self.files[key]
        assert len(data) == size and sha == sha256 == hashlib.sha256(data).hexdigest()
        if accessible != public:
            raise AppError(409, "STORAGE_POLICY_UNSAFE", "测试访问策略不符")

    def delete(self, key):
        if self.fail_delete:
            raise AppError(503, "STORAGE_DELETE_UNCONFIRMED", "测试删除失败")
        self.files.pop(key, None)

    def url(self, key):
        return "https://public.example.invalid/" + key

    def presign(self, key, **kwargs):
        return "https://private.example.invalid/" + key


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeCloud()
    monkeypatch.setattr("app.domains.storage.service.adapter", lambda *_: fake)
    monkeypatch.setattr("app.domains.storage.service.Adapter", lambda *_: fake)
    monkeypatch.setattr("app.domains.storage.publications.adapter", lambda *_: fake)
    return fake


def location(client, headers, mode="private"):
    result = client.post(
        "/api/v1/settings/storage-locations",
        headers=headers,
        json=dict(
            name="测试存储",
            provider="oss",
            region="cn-hangzhou",
            bucket="fuma-test",
            prefix="fuma/test",
            read_mode=mode,
            access_key_id="test-only-id",
            access_key_secret="test-only-placeholder",
        ),
    )
    assert result.status_code == 200, result.text
    assert "credentials" not in result.text and "test-only" not in result.text
    row = result.json()
    tested = client.post(
        f"/api/v1/settings/storage-locations/{row['id']}/test",
        headers={**headers, "If-Match": '"1"'},
    )
    assert tested.status_code == 200, tested.text
    execute_task(client.app.state.engine, client.app.state.settings, tested.json()["task_id"])
    return client.get(f"/api/v1/settings/storage-locations/{row['id']}").json()


def test_cloud_probe_rotation_failure_preserves_credentials_and_retries_cleanup(
    client, configured_app, cloud
):
    headers, _ = configured_app
    row = location(client, headers)
    assert row["status"] == "ready" and row["capabilities"]["cleanup"] == "passed"
    with Session(client.app.state.engine) as db:
        old = db.get(StorageLocation, UUID(row["id"])).encrypted_credentials
    cloud.fail_upload = True
    result = client.put(
        f"/api/v1/settings/storage-locations/{row['id']}/credentials",
        headers={**headers, "If-Match": f'"{row["revision"]}"'},
        json={"access_key_id": "candidate-id", "access_key_secret": "candidate-placeholder"},
    )
    assert result.status_code == 200, result.text
    execute_task(client.app.state.engine, client.app.state.settings, result.json()["task_id"])
    with Session(client.app.state.engine) as db:
        current = db.get(StorageLocation, UUID(row["id"]))
        assert current.encrypted_credentials == old
        assert current.status == "failed"
    cloud.fail_upload = False
    row = client.get(f"/api/v1/settings/storage-locations/{row['id']}").json()
    result = client.post(
        f"/api/v1/settings/storage-locations/{row['id']}/test",
        headers={**headers, "If-Match": f'"{row["revision"]}"'},
    )
    execute_task(client.app.state.engine, client.app.state.settings, result.json()["task_id"])
    with Session(client.app.state.engine) as db:
        current = db.get(StorageLocation, UUID(row["id"]))
        assert current.status == "ready" and current.encrypted_credentials != old
        assert current.candidate_credentials is None


def test_root_prefix_accepts_platform_directories_and_reuses_credential_profile(
    client, configured_app
):
    headers, _ = configured_app
    first = client.post(
        "/api/v1/settings/storage-locations",
        headers=headers,
        json={
            "name": "Debug 根目录",
            "provider": "oss",
            "region": "cn-hangzhou",
            "bucket": "fuma-debug",
            "prefix": "/",
            "read_mode": "private",
            "credential_name": "Joice COS 发布凭据",
            "access_key_id": "shared-access-id",
            "access_key_secret": "shared-access-secret",
        },
    )
    assert first.status_code == 200, first.text
    debug = first.json()
    assert debug["prefix"] == "" and debug["credential_id"]

    profiles = client.get("/api/v1/settings/storage-credentials", headers=headers)
    assert profiles.status_code == 200, profiles.text
    profile = profiles.json()["items"][0]
    assert profile["location_count"] == 1
    assert "shared-access-secret" not in profiles.text

    release = client.post(
        "/api/v1/settings/storage-locations",
        headers=headers,
        json={
            "name": "Release 根目录",
            "provider": "oss",
            "region": "cn-hangzhou",
            "bucket": "fuma-release",
            "prefix": "",
            "read_mode": "private",
            "credential_id": profile["id"],
        },
    )
    assert release.status_code == 200, release.text
    assert release.json()["credential_id"] == debug["credential_id"]
    profiles = client.get("/api/v1/settings/storage-credentials", headers=headers).json()
    assert profiles["items"][0]["location_count"] == 2


def test_joice_archive_manifest_requires_verified_inner_apk(tmp_path):
    apk = b"synthetic apk payload"
    digest = hashlib.sha256(apk).hexdigest()
    path = tmp_path / "2026092202.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("Joice-debug.apk", apk)
        archive.writestr("Joice-debug.apk.sha256", f"{digest}  Joice-debug.apk\n")
        archive.writestr("build-info.json", json.dumps({"commit": "a" * 40}))
    manifest = _archive_manifest(path, "android/2026092202.zip")
    assert manifest == {
        "schema_version": "archive-1",
        "platform": "android",
        "file_name": "Joice-debug.apk",
        "entry_name": "Joice-debug.apk",
    }


def test_public_copy_reclaim_failure_never_reopens_download(
    client, configured_app, cloud, monkeypatch
):
    headers, app = configured_app
    private = location(client, headers)
    default = client.post(
        f"/api/v1/settings/storage-locations/{private['id']}/make-default",
        headers={**headers, "If-Match": f'"{private["revision"]}"'},
    )
    assert default.status_code == 200, default.text
    public = location(client, headers, "public")
    data = ipa()
    upload = start(client, headers, app, data, monkeypatch)
    send(client, headers, upload, data)
    client.post(f"/api/v1/uploads/{upload['id']}/complete", headers=headers)
    package = process(client, upload, keep_cloud=True)
    version = client.post(
        f"/api/v1/apps/{app['id']}/versions",
        headers=headers,
        json={"display_name": "1.0", "mode": "release", "release_notes": "云发布"},
    ).json()
    result = client.post(
        f"/api/v1/versions/{version['id']}/publications",
        headers=headers,
        json={"platform": "ios", "package_ids": [package], "public_storage_id": public["id"]},
    )
    assert result.status_code == 201, result.text
    publication = result.json()
    pid = publication["id"]
    result = client.post(
        f"/api/v1/publications/{pid}/publish", headers={**headers, "If-Match": '"1"'}
    )
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "draft" and result.json()["access_state"] == "publishing"
    execute_task(
        client.app.state.engine, client.app.state.settings, result.json()["access_task_id"]
    )
    row = client.get(f"/api/v1/publications/{pid}").json()
    assert row["state"] == "published" and row["access_state"] == "public", row
    assert client.get(f"/api/v1/catalog/publications/{pid}").status_code == 200
    assert (
        client.post(
            f"/api/v1/catalog/publications/{pid}/grants",
            headers=headers,
            json={"package_id": package},
        ).json()["expires_at"]
        is None
    )
    cloud.fail_delete = True
    result = client.post(
        f"/api/v1/publications/{pid}/unpublish",
        headers={**headers, "If-Match": f'"{row["revision"]}"'},
    )
    execute_task(
        client.app.state.engine, client.app.state.settings, result.json()["access_task_id"]
    )
    row = client.get(f"/api/v1/publications/{pid}").json()
    assert row["state"] == "unpublished" and row["access_state"] == "reclaim_failed"
    assert client.get(f"/api/v1/catalog/publications/{pid}").status_code in {403, 404}
    assert (
        client.post(
            f"/api/v1/publications/{pid}/publish",
            headers={**headers, "If-Match": f'"{row["revision"]}"'},
        ).status_code
        == 409
    )
    cloud.fail_delete = False
    result = client.post(
        f"/api/v1/publications/{pid}/retry-access",
        headers={**headers, "If-Match": f'"{row["revision"]}"'},
    )
    execute_task(
        client.app.state.engine, client.app.state.settings, result.json()["access_task_id"]
    )
    row = client.get(f"/api/v1/publications/{pid}").json()
    assert row["access_state"] == "reclaimed"
    with Session(client.app.state.engine) as db:
        originals = list(db.scalars(select(StoredObject).where(StoredObject.kind == "canonical")))
        assert len(originals) == 1 and originals[0].state == "ready"
        assert cloud.files[originals[0].object_key][2] is False


@pytest.mark.parametrize("provider,bucket", [("cos", "fuma-test-123456789"), ("oss", "fuma-test")])
def test_official_sdk_signatures_use_https_provider_origin(provider, bucket):
    from types import SimpleNamespace

    client = Adapter(
        SimpleNamespace(
            provider=provider,
            region="ap-guangzhou" if provider == "cos" else "cn-hangzhou",
            bucket=bucket,
            prefix="fuma",
            read_mode="private",
        ),
        {"access_key_id": "test-only", "access_key_secret": "test-only-placeholder"},
    )
    url = client.presign("fuma/file.bin")
    assert url.startswith(client.origin + "/fuma/file.bin?")
    assert "test-only-placeholder" not in url
    with pytest.raises(AppError):
        client.key("other/file.bin")


def test_list_objects_normalizes_cos_and_oss_pagination():
    from types import SimpleNamespace
    from unittest.mock import Mock

    import alibabacloud_oss_v2 as oss

    credentials = {"access_key_id": "fixture", "access_key_secret": "fixture-not-live"}
    cos = Adapter(
        SimpleNamespace(
            provider="cos",
            region="ap-guangzhou",
            bucket="test-123456789",
            prefix="fuma",
            read_mode="private",
        ),
        credentials,
    )
    cos.client = Mock()
    cos.client.list_objects.return_value = {
        "Contents": [{"Key": "fuma/debug/app.apk", "Size": 7}],
        "IsTruncated": True,
        "NextMarker": "fuma/debug/app.apk",
    }
    assert cos.list_objects("fuma/debug", limit=10, cursor="start") == {
        "items": [{"key": "fuma/debug/app.apk", "size": 7, "sha256": None}],
        "next_cursor": "fuma/debug/app.apk",
    }
    kwargs = cos.client.list_objects.call_args.kwargs
    assert kwargs["Prefix"] == "fuma/debug/" and kwargs["Marker"] == "start"

    oss_client = Adapter(
        SimpleNamespace(
            provider="oss",
            region="cn-hangzhou",
            bucket="test-bucket",
            prefix="fuma",
            read_mode="private",
        ),
        credentials,
    )
    oss_client.client = Mock()
    oss_client.client.list_objects_v2.return_value = oss.ListObjectsV2Result(
        contents=[oss.ObjectProperties(key="fuma/debug/app.ipa", size=9)],
        is_truncated=True,
        next_continuation_token="next",
    )
    assert oss_client.list_objects("fuma/debug") == {
        "items": [{"key": "fuma/debug/app.ipa", "size": 9, "sha256": None}],
        "next_cursor": "next",
    }
    request = oss_client.client.list_objects_v2.call_args.kwargs["request"]
    assert request.prefix == "fuma/debug/"


def test_sdk_specific_metadata_versioning_and_nested_delete_errors(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import alibabacloud_oss_v2 as oss
    from alibabacloud_oss_v2.exceptions import OperationError, ServiceError

    credentials = {"access_key_id": "fixture", "access_key_secret": "fixture-not-live"}
    location = SimpleNamespace(
        provider="cos",
        region="ap-guangzhou",
        bucket="test-123456789",
        prefix="fuma",
        read_mode="private",
    )
    client = Adapter(location, credentials)
    client.client = Mock()
    file = tmp_path / "object.bin"
    file.write_bytes(b"test")
    client.put("fuma/object.bin", file, "a" * 64)
    assert client.client.upload_file.call_args.kwargs["Metadata"] == {"x-cos-meta-sha256": "a" * 64}
    location = SimpleNamespace(
        provider="oss",
        region="cn-hangzhou",
        bucket="test-bucket",
        prefix="fuma",
        read_mode="public",
    )
    client = Adapter(location, credentials)
    client.client = Mock()
    client.client.get_bucket_versioning.return_value = oss.GetBucketVersioningResult(
        version_status="Enabled"
    )
    with pytest.raises(AppError) as raised:
        client.check_bucket()
    assert raised.value.code == "STORAGE_POLICY_UNSAFE"
    with pytest.raises(AppError):
        client.delete("fuma/object.bin")
    client.client.delete_object.assert_not_called()
    client.client.get_bucket_versioning.return_value = oss.GetBucketVersioningResult()
    client.client.head_object.side_effect = OperationError(
        name="HeadObject",
        error=ServiceError(
            status_code=404,
            code="NoSuchKey",
            request_id="fixture",
            message="missing",
            ec="",
            timestamp="",
            request_target="",
        ),
    )
    monkeypatch.setattr(client, "anonymous_status", lambda _: 404)
    client.delete("fuma/object.bin")
    client.client.head_object.side_effect = OperationError(
        name="HeadObject",
        error=ServiceError(
            status_code=403,
            code="AccessDenied",
            request_id="fixture",
            message="denied",
            ec="",
            timestamp="",
            request_target="",
        ),
    )
    with pytest.raises(AppError):
        client.delete("fuma/object.bin")
