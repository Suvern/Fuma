"""Native PostgreSQL CI callback, trust boundary and resumable stage tests."""

import base64
import copy
import hashlib
import json
import secrets
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.actions import router
from app.core.config import Settings
from app.core.errors import AppError
from app.domains.applications.models import (
    AllowedPackageIdRecord,
    AppRecord,
    AppStorageBindingRecord,
)
from app.domains.auth.models import User
from app.domains.auth.service import password_hasher, token_hash, utcnow
from app.domains.distribution.actions import process_event, verify_source
from app.domains.distribution.models import (
    ChatRecord,
    DebugRecord,
    DeliveryRecord,
    EventRecord,
    PackageIngestionRecord,
    RuleRecord,
    TaskRecord,
)
from app.domains.distribution.service import RetryLater
from app.domains.library.models import PublicationRecord
from app.domains.storage.models import StorageLocation
from app.domains.system.models import SystemState
from app.infrastructure.database import Base, build_engine
from app.main import create_app

SHA = "a" * 40


@pytest.fixture
def client(tmp_path, isolated_database_url):
    settings = Settings(
        state_dir=tmp_path / "state",
        encryption_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        database_url=isolated_database_url,
    )
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(SystemState(id=1, initialized_at=utcnow()))
        db.add(
            User(
                kind="local",
                username="admin",
                display_name="admin",
                password_hash=password_hasher.hash("test-password-123"),
            )
        )
        db.add(
            ChatRecord(
                chat_id="oc_group",
                name="构建通知群",
                membership="joined",
                send_status="unverified",
                synced_at=utcnow(),
            )
        )
        db.commit()
    app = create_app(settings)
    if not any(getattr(r, "operation_id", None) == "receive_actions_event" for r in app.routes):
        app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    engine.dispose()


def setup_rule(client):
    context = client.get("/api/v1/auth/browser-context").json()
    headers = {"Origin": client.app.state.settings.site_url, "X-CSRF-Token": context["csrf_token"]}
    result = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={
            "username": "admin",
            "password": "test-password-123",
        },
    )
    assert result.status_code == 200, result.text
    headers["X-CSRF-Token"] = result.json()["csrf_token"]
    with Session(client.app.state.engine) as db:
        app = AppRecord(
            name="Test",
            public_slug="test",
            description="",
            platforms=["android"],
            enabled=True,
            created_at=utcnow(),
            updated_at=utcnow(),
            repository={
                "connector_id": str(uuid4()),
                "repository_id": "42",
                "full_name": "team/mobile",
                "private": True,
            },
        )
        db.add(app)
        db.commit()
        app_id = app.id
    payload = {
        "name": "构建",
        "workflow_path": ".github/workflows/build.yml",
        "allowed_branches": ["main"],
        "allowed_tags": ["v*"],
        "asset_patterns": ["*.apk"],
        "chat_ids": ["oc_group"],
        "enabled": True,
    }
    result = client.post(f"/api/v1/apps/{app_id}/actions-rules", headers=headers, json=payload)
    assert result.status_code == 201, result.text
    return headers, result.json(), str(app_id)


def event_body():
    return {
        "repository_id": "42",
        "run_id": "12",
        "run_attempt": 1,
        "head_sha": SHA,
        "release_id": "3",
        "asset_ids": ["4"],
    }


def submit(client, rule, body=None):
    return client.post(
        f"/api/v1/integrations/github-actions/{rule['rule']['id']}/events",
        headers={"Authorization": "Bearer " + rule["token"]},
        json=body or event_body(),
    )


class Provider:
    def __init__(self):
        self.run = {
            "id": 12,
            "run_attempt": 1,
            "head_sha": SHA,
            "repository": {"id": 42},
            "head_repository": {"id": 42},
            "event": "push",
            "pull_requests": [],
            "workflow_id": 6,
            "path": ".github/workflows/build.yml",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
        }
        self.asset = {
            "id": 4,
            "name": "demo.apk",
            "size": 1024,
            "updated_at": "2026-10-01T00:00:00Z",
            "digest": None,
        }
        self.release = {"id": 3, "tag_name": "v1", "draft": False, "assets": [self.asset]}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        pass

    def get_repository(self, name):
        return {"id": 42}

    def get_run(self, name, run, attempt):
        return copy.deepcopy(self.run)

    def get_workflow(self, name, workflow):
        return {"path": self.run["path"]}

    def get_release(self, name, release):
        return copy.deepcopy(self.release)

    def list_assets(self, name, release):
        return [copy.deepcopy(self.asset)]

    def tag_commit(self, name, tag):
        return SHA


def test_rule_callback_deduplication_rotation_and_revoke(client):
    headers, rule, app_id = setup_rule(client)
    result = submit(client, rule)
    assert result.status_code == 202, result.text
    event_id = result.json()["event_id"]
    duplicate = submit(client, rule, {**event_body(), "asset_ids": ["4", "4"]})
    assert duplicate.status_code == 202 and duplicate.json()["event_id"] == event_id
    assert duplicate.json()["duplicate"]
    changed = submit(client, rule, {**event_body(), "head_sha": "b" * 40})
    assert changed.status_code == 409
    with Session(client.app.state.engine) as db:
        record = db.get(RuleRecord, UUID(rule["rule"]["id"]))
        assert record.token_hash == token_hash(rule["token"])
        assert len(db.scalars(select(EventRecord)).all()) == 1
        assert len(db.scalars(select(TaskRecord)).all()) == 1
    headers["If-Match"] = '"1"'
    rotated = client.post(
        f"/api/v1/actions-rules/{rule['rule']['id']}/token/rotate", headers=headers
    )
    assert rotated.status_code == 200
    assert submit(client, rule).status_code == 401
    rule["token"] = rotated.json()["token"]
    assert submit(client, rule).status_code == 202
    headers["If-Match"] = '"2"'
    assert (
        client.delete(f"/api/v1/actions-rules/{rule['rule']['id']}", headers=headers).status_code
        == 204
    )
    assert submit(client, rule).status_code == 401
    assert client.get(f"/api/v1/build-events/{event_id}").status_code == 200
    assert client.get(f"/api/v1/apps/{app_id}/build-events").json()["total"] == 1


@pytest.mark.parametrize("channel", ["debug", "release"])
def test_cos_event_is_idempotent_and_queues_object_check(client, monkeypatch, channel):
    headers, rule, app_id = setup_rule(client)
    storage_id = uuid4()
    with Session(client.app.state.engine) as db:
        db.add(
            StorageLocation(
                id=storage_id,
                name="COS Debug",
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
        db.flush()
        db.add(
            AppStorageBindingRecord(
                app_id=UUID(app_id),
                channel=channel,
                storage_location_id=storage_id,
                object_prefix=channel,
                revision=1,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        db.add(
            AllowedPackageIdRecord(
                app_id=UUID(app_id),
                platform="android",
                mode=channel,
                normalized_identifier="com.example.app",
                identifier="com.example.app",
            )
        )
        db.commit()
    body = {
        "schema_version": "2",
        "event_id": "joice-build-123",
        "app_id": app_id,
        "channel": channel,
        "build": {
            "version": "1.2.3",
            "build_number": "123",
            "commit_sha": SHA,
            "workflow_run_id": "456",
            "created_at": "2026-10-16T10:00:00Z",
        },
        "object": {
            "key": f"fuma/test/{channel}/1.2.3/123/package.apk",
            "size": 7,
            "sha256": hashlib.sha256(b"package").hexdigest(),
            "content_type": "application/vnd.android.package-archive",
        },
        "manifest": {
            "key": f"fuma/test/{channel}/1.2.3/123/manifest.json",
            "sha256": hashlib.sha256(
                b'{"schema_version":"1","platform":"android","file_name":"app.apk"}'
            ).hexdigest(),
        },
    }
    endpoint = f"/api/v1/integrations/github-actions/{rule['rule']['id']}/cos-events"
    first = client.post(endpoint, headers={"Authorization": "Bearer " + rule["token"]}, json=body)
    assert first.status_code == 202, first.text
    duplicate = client.post(
        endpoint,
        headers={"Authorization": "Bearer " + rule["token"]},
        json={**body, "object": {**body["object"], "etag": "etag-1"}},
    )
    assert duplicate.status_code == 202 and duplicate.json()["duplicate"]
    changed = client.post(
        endpoint,
        headers={"Authorization": "Bearer " + rule["token"]},
        json={**body, "object": {**body["object"], "size": 8}},
    )
    assert changed.status_code == 409
    with Session(client.app.state.engine) as db:
        ingestion = db.scalar(select(PackageIngestionRecord))
        assert ingestion and ingestion.state == "received"
        assert ingestion.task_id is not None
        task = db.get(TaskRecord, ingestion.task_id)
        assert task and task.kind == "cos_package_ingest"

        class HeadOnlyClient:
            def head(self, key):
                if key == body["object"]["key"]:
                    return body["object"]["size"], None
                return 1, None

            def download(self, key, path, *, expected_size=None, max_size=None):
                import hashlib

                content = (
                    b"package"
                    if key == body["object"]["key"]
                    else b'{"schema_version":"1","platform":"android","file_name":"app.apk"}'
                )
                if expected_size is not None:
                    assert len(content) == expected_size
                if max_size is not None:
                    assert len(content) <= max_size
                path.write_bytes(content)
                return len(content), hashlib.sha256(content).hexdigest()

            def verify(self, key, size, sha256, *, public=False, full=False):
                assert key.endswith("package.apk") and size == 7 and len(sha256) == 64

        monkeypatch.setattr(
            "app.domains.storage.package_ingestion.adapter",
            lambda settings, location: HeadOnlyClient(),
        )
        monkeypatch.setattr(
            "app.domains.storage.cos_ingestion.adapter",
            lambda settings, location: HeadOnlyClient(),
        )
        from app.domains.storage.package_ingestion import verify_object

        verify_object(db, client.app.state.settings, task)
        assert db.get(PackageIngestionRecord, ingestion.id).state == "verified"
        parse_task = db.get(TaskRecord, ingestion.task_id)
        outbox = client.app.state.settings.parser_outbox
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / f"{parse_task.id}.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "sha256": body["object"]["sha256"],
                    "metadata": {
                        "package_identifier": "com.example.app",
                        "version_name": "1.2.3",
                        "build_number": "123",
                        "min_os": None,
                        "architectures": [],
                        "signer_fingerprints": [],
                        "signature_status": "测试签名",
                        "parser_version": "fixture",
                    },
                }
            )
        )
        from app.domains.storage.cos_ingestion import parse_and_persist

        parse_and_persist(db, client.app.state.settings, parse_task)
        assert db.get(PackageIngestionRecord, ingestion.id).state == (
            "ready" if channel == "debug" else "pending_publish"
        )
        if channel == "debug":
            assert db.scalar(select(DebugRecord)) is not None
            delivery = db.scalar(
                select(DeliveryRecord).where(DeliveryRecord.rule_id == UUID(rule["rule"]["id"]))
            )
            assert delivery and delivery.kind == "build_ready" and delivery.state == "queued"
            notification_task = db.scalar(
                select(TaskRecord).where(
                    TaskRecord.dedupe_key == f"cos_notification:{ingestion.id}"
                )
            )
            assert (
                notification_task and str(delivery.id) in notification_task.payload["delivery_ids"]
            )
        else:
            assert db.scalar(select(DebugRecord)) is None
            assert ingestion.publication_id is not None
            publication = db.get(PublicationRecord, ingestion.publication_id)
            assert publication and publication.state == "draft"
        ingestion_id = ingestion.id
    if channel == "release":
        listing = client.get(
            f"/api/v1/apps/{app_id}/package-ingestions?state=pending_publish&channel=release",
            headers=headers,
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 1
        assert listing.json()["items"][0]["publication_revision"] == 1
        monkeypatch.setattr("app.api.library.adapter", lambda settings, location: HeadOnlyClient())
        published = client.post(
            f"/api/v1/package-ingestions/{ingestion_id}/publish",
            headers={**headers, "If-Match": '"1"'},
        )
        assert published.status_code == 200, published.text
        assert published.json()["state"] == "published"
    with Session(client.app.state.engine) as db:
        ingestion = db.get(PackageIngestionRecord, ingestion_id)
        parse_task = db.get(TaskRecord, ingestion.task_id)
        ingestion.state = "failed"
        parse_task.state = "failed"
        db.commit()
    retry_headers = {**headers, "Idempotency-Key": str(uuid4())}
    retry = client.post(f"/api/v1/package-ingestions/{ingestion_id}/retry", headers=retry_headers)
    assert retry.status_code == 202, retry.text
    replay = client.post(f"/api/v1/package-ingestions/{ingestion_id}/retry", headers=retry_headers)
    assert replay.status_code == 202 and replay.json() == retry.json()


@pytest.mark.parametrize(
    "change",
    [
        {"head_repository": {"id": 999}},
        {"event": "pull_request_target"},
        {"head_sha": "b" * 40},
        {"run_attempt": 2},
        {"head_branch": "untrusted"},
        {"path": ".github/workflows/evil.yml"},
        {"pull_requests": [{"number": 1}]},
    ],
)
def test_provider_trust_validation_rejects_spoofing(client, change):
    _, rule, _ = setup_rule(client)
    result = submit(client, rule)
    with Session(client.app.state.engine) as db:
        event = db.get(EventRecord, UUID(result.json()["event_id"]))
        provider = Provider()
        provider.run.update(change)
        with pytest.raises(AppError):
            verify_source(provider, event)


def test_wait_run_cache_then_notify_resumes_without_duplicate(client, monkeypatch, tmp_path):
    _, rule, _ = setup_rule(client)
    event_id = UUID(submit(client, rule).json()["event_id"])
    provider = Provider()
    provider.run.update(status="in_progress", conclusion=None)
    monkeypatch.setattr("app.domains.distribution.actions.get_github_client", lambda *a: provider)
    monkeypatch.setattr("app.domains.distribution.packages.get_github_client", lambda *a: provider)
    with Session(client.app.state.engine) as db:
        with pytest.raises(RetryLater):
            process_event(db, client.app.state.settings, event_id)
        assert db.get(EventRecord, event_id).state == "waiting_run"
        assert not db.scalars(select(DebugRecord)).all()
        provider.run.update(status="completed", conclusion="success")
        with pytest.raises(RetryLater):
            process_event(db, client.app.state.settings, event_id)
        assert db.get(EventRecord, event_id).state == "caching"
        entries = db.scalars(select(DebugRecord)).all()
        assert len(entries) == 1
        assert not db.scalars(select(DeliveryRecord)).all()
        entries[0].cache_state = "ready"
        entries[0].sha256 = "c" * 64
        entries[0].cache_record.cache_state = "ready"
        cached = tmp_path / "synthetic.apk"
        cached.write_bytes(b"synthetic-package")
        monkeypatch.setattr(
            "app.domains.distribution.package_metadata.cache_path", lambda *_: cached
        )
        db.commit()
        with pytest.raises(RetryLater):
            process_event(db, client.app.state.settings, event_id)
        assert not db.scalars(select(DeliveryRecord)).all()
        settings = client.app.state.settings
        request = next(settings.parser_inbox.glob("*.json"))
        (settings.parser_outbox / request.name).write_text(
            json.dumps({"ok": True, "sha256": "c" * 64, "metadata": {"build_number": "2026100701"}})
        )
        with pytest.raises(RetryLater):
            process_event(db, settings, event_id)
        deliveries = db.scalars(select(DeliveryRecord)).all()
        assert len(deliveries) == 1
        assert deliveries[0].card["build_number"] == "2026100701"
        assert "**Build**：2026100701" in deliveries[0].card["summary"]
        assert deliveries[0].card["page_url"].endswith("/apps/" + str(entries[0].app_id))
        assert deliveries[0].card["sub_button_url"] == deliveries[0].card["page_url"]
        deliveries[0].state = "succeeded"
        db.commit()
        process_event(db, client.app.state.settings, event_id)
        assert db.get(EventRecord, event_id).state == "succeeded"
        process_event(db, client.app.state.settings, event_id)
        assert len(db.scalars(select(DeliveryRecord)).all()) == 1


def test_pending_event_stops_after_token_revoked(client, monkeypatch):
    headers, rule, _ = setup_rule(client)
    event_id = UUID(submit(client, rule).json()["event_id"])
    headers["If-Match"] = '"1"'
    assert (
        client.post(
            f"/api/v1/actions-rules/{rule['rule']['id']}/token/revoke", headers=headers
        ).status_code
        == 204
    )
    with Session(client.app.state.engine) as db:
        with pytest.raises(AppError, match="撤销"):
            process_event(db, client.app.state.settings, event_id)
        assert db.get(EventRecord, event_id).state == "failed"
        assert not db.scalars(select(DebugRecord)).all()


def test_cache_failure_notifies_without_download_link(client, monkeypatch):
    _, rule, _ = setup_rule(client)
    event_id = UUID(submit(client, rule).json()["event_id"])
    provider = Provider()
    monkeypatch.setattr("app.domains.distribution.actions.get_github_client", lambda *a: provider)
    monkeypatch.setattr("app.domains.distribution.packages.get_github_client", lambda *a: provider)
    with Session(client.app.state.engine) as db:
        with pytest.raises(RetryLater):
            process_event(db, client.app.state.settings, event_id)
        entry = db.scalar(select(DebugRecord))
        entry.cache_state, entry.cache_error_code = "failed", "CACHE_CAPACITY_EXCEEDED"
        entry.cache_record.cache_state = "failed"
        entry.cache_record.cache_error_code = "CACHE_CAPACITY_EXCEEDED"
        db.commit()
        with pytest.raises(RetryLater):
            process_event(db, client.app.state.settings, event_id)
        delivery = db.scalar(select(DeliveryRecord))
        assert delivery.card["page_url"] is None
        assert delivery.card["file_names"] == []
        assert delivery.kind == "build_failed"
        delivery.state = "succeeded"
        db.commit()
        process_event(db, client.app.state.settings, event_id)
        assert db.get(EventRecord, event_id).state == "failed"
    result = client.get(f"/api/v1/build-events/{event_id}").json()
    assert result["retryable_stages"] == ["cache"]


def test_unknown_delivery_never_replayed_by_event_retry(client, monkeypatch):
    headers, rule, _ = setup_rule(client)
    event_id = UUID(submit(client, rule).json()["event_id"])
    provider = Provider()
    monkeypatch.setattr("app.domains.distribution.actions.get_github_client", lambda *a: provider)
    monkeypatch.setattr("app.domains.distribution.packages.get_github_client", lambda *a: provider)
    with Session(client.app.state.engine) as db:
        with pytest.raises(RetryLater):
            process_event(db, client.app.state.settings, event_id)
        entry = db.scalar(select(DebugRecord))
        entry.cache_state = "ready"
        entry.cache_record.cache_state = "ready"
        db.commit()
        with pytest.raises(RetryLater):
            process_event(db, client.app.state.settings, event_id)
        db.scalar(select(DeliveryRecord)).state = "unknown"
        db.commit()
        process_event(db, client.app.state.settings, event_id)
        assert db.get(EventRecord, event_id).state == "unknown"
    headers["Idempotency-Key"] = str(uuid4())
    retry = client.post(
        f"/api/v1/build-events/{event_id}/retry", headers=headers, json={"stage": "notify"}
    )
    assert retry.status_code == 409
    assert "未知投递" in retry.json()["error"]["message"]


def test_verified_failed_run_notifies_but_untrusted_run_does_not(client, monkeypatch):
    _, rule, _ = setup_rule(client)
    event_id = UUID(submit(client, rule).json()["event_id"])
    provider = Provider()
    provider.run["conclusion"] = "failure"
    monkeypatch.setattr("app.domains.distribution.actions.get_github_client", lambda *a: provider)
    with Session(client.app.state.engine) as db:
        with pytest.raises(AppError):
            process_event(db, client.app.state.settings, event_id)
        delivery = db.scalar(select(DeliveryRecord))
        assert delivery.kind == "build_failed" and delivery.card["page_url"] is None
        assert not db.scalars(select(DebugRecord)).all()


def test_rule_can_be_disabled_after_bot_leaves_group(client):
    headers, rule, _ = setup_rule(client)
    with Session(client.app.state.engine) as db:
        db.get(ChatRecord, "oc_group").membership = "left"
        db.commit()
    headers["If-Match"] = '"1"'
    result = client.patch(
        f"/api/v1/actions-rules/{rule['rule']['id']}", headers=headers, json={"enabled": False}
    )
    assert result.status_code == 200 and not result.json()["enabled"]
    headers["If-Match"] = '"2"'
    result = client.patch(
        f"/api/v1/actions-rules/{rule['rule']['id']}", headers=headers, json={"enabled": True}
    )
    assert result.status_code == 422


def test_ci_bearer_cannot_cross_repository_or_use_browser_session(client):
    headers, rule, _ = setup_rule(client)
    url = f"/api/v1/integrations/github-actions/{rule['rule']['id']}/events"
    assert client.post(url, headers=headers, json=event_body()).status_code == 401
    assert submit(client, rule, {**event_body(), "repository_id": "99"}).status_code == 403
    body = event_body()
    body["download_url"] = "https://example.test/anything.apk"
    assert submit(client, rule, body).status_code == 422


@pytest.mark.parametrize("change", [{"draft": True}, {"id": 999}, {"assets": []}])
def test_release_membership_and_draft_fail_closed(client, change):
    _, rule, _ = setup_rule(client)
    event_id = UUID(submit(client, rule).json()["event_id"])
    provider = Provider()
    provider.release.update(change)
    with Session(client.app.state.engine) as db:
        with pytest.raises(AppError):
            verify_source(provider, db.get(EventRecord, event_id))


def test_tag_commit_must_match_run(client):
    _, rule, _ = setup_rule(client)
    event_id = UUID(submit(client, rule).json()["event_id"])
    provider = Provider()
    provider.tag_commit = lambda *args: "b" * 40
    with Session(client.app.state.engine) as db:
        with pytest.raises(AppError, match="提交不一致"):
            verify_source(provider, db.get(EventRecord, event_id))
