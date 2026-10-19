"""Feishu binding and delivery races using PostgreSQL plus provider HTTP fixtures."""

import base64
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.feishu import router
from app.core.config import Settings
from app.domains.auth.models import AuthSession, User
from app.domains.auth.service import password_hasher, utcnow
from app.domains.distribution.feishu import create_delivery, send_delivery, sync_chats
from app.domains.distribution.models import ChatRecord, DeliveryRecord, IntegrationState, TaskRecord
from app.domains.distribution.service import RetryLater
from app.domains.github.crypto import SecretBox
from app.domains.system.models import SystemState
from app.infrastructure.database import Base, build_engine
from app.integrations.feishu import FeishuClient
from app.main import create_app


@pytest.fixture
def feishu_fixture(monkeypatch, tmp_path, isolated_database_url):
    settings = Settings(
        database_url=isolated_database_url,
        encryption_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        cache_dir=tmp_path,
        state_dir=tmp_path / "state",
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
                password_hash=password_hasher.hash("Test-password-123"),
            )
        )
        db.commit()
    provider = {
        "tenant": "tenant-test",
        "sent": 0,
        "on_oauth": None,
        "on_bot": None,
        "on_send": None,
    }

    def handle(request):
        path = request.url.path
        if path.endswith("tenant_access_token/internal"):
            if b"invalid-candidate-secret" in request.content:
                return httpx.Response(200, json={"code": 999})
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "synthetic-app-token"}
            )
        if path.endswith("oauth/token"):
            if provider["on_oauth"]:
                provider["on_oauth"]()
            return httpx.Response(200, json={"code": 0, "access_token": "synthetic-user-token"})
        if path.endswith("user_info"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "tenant_key": provider["tenant"],
                        "open_id": "open-user",
                        "name": "测试用户",
                    },
                },
            )
        if path.endswith("/bot/v3/info/"):
            if provider["on_bot"]:
                provider["on_bot"]()
            return httpx.Response(
                200, json={"code": 0, "bot": {"open_id": "bot-test", "app_name": "测试机器人"}}
            )
        if path.endswith("/im/v1/chats"):
            second = "page_token" in request.url.params
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [
                            {
                                "chat_id": "chat-last" if second else "chat-first",
                                "name": "最后一页测试群" if second else "第一页",
                            }
                        ],
                        "has_more": not second,
                        "page_token": None if second else "page-two",
                    },
                },
            )
        if path.endswith("/im/v1/messages"):
            provider["sent"] += 1
            if provider["on_send"]:
                provider["on_send"]()
            return httpx.Response(200, json={"code": 0, "data": {"message_id": "message-test"}})
        return httpx.Response(404, json={"code": 999})

    def factory(app_id, secret):
        return FeishuClient(app_id, secret, transport=httpx.MockTransport(handle))

    monkeypatch.setattr("app.api.feishu.FeishuClient", factory)
    monkeypatch.setattr("app.domains.distribution.feishu.FeishuClient", factory)
    app = create_app(settings)
    if not any(getattr(route, "path", "") == "/api/v1/settings/feishu" for route in app.routes):
        app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        context = client.get("/api/v1/auth/browser-context").json()
        headers = {"Origin": settings.site_url, "X-CSRF-Token": context["csrf_token"]}
        response = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={
                "username": "admin",
                "password": "Test-password-123",
            },
        )
        assert response.status_code == 200
        headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client, provider, settings, headers
    engine.dispose()


def configure(client, headers):
    result = client.put(
        "/api/v1/settings/feishu",
        headers={**headers, "If-Match": '"0"'},
        json={
            "app_id": "cli_synthetic",
            "app_secret": "synthetic-app-secret",
            "enabled": True,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def bind(client, headers):
    configured = configure(client, headers)
    started = client.post("/api/v1/settings/feishu/binding/start", headers=headers, json={})
    assert started.status_code == 200, started.text
    raw_state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    result = client.get(
        "/api/v1/auth/feishu/callback",
        params={"state": raw_state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert result.status_code == 303, result.text
    proof = client.get("/api/v1/settings/feishu/binding/proof").json()
    confirmed = client.post(
        "/api/v1/settings/feishu/binding/confirm",
        headers={**headers, "If-Match": f'"{configured["revision"]}"'},
        json={"binding_id": proof["binding_id"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json(), raw_state


def test_trusted_binding_preserves_admin_and_rejects_replay(feishu_fixture):
    client, _, _, headers = feishu_fixture
    result, raw_state = bind(client, headers)
    assert result["tenant_key"] == "tenant-test" and result["verified"]
    assert client.get("/api/v1/auth/me").json()["user"]["role"] == "admin"
    replay = client.get(
        "/api/v1/auth/feishu/callback",
        params={"state": raw_state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert "OAUTH_STATE_INVALID" in replay.headers["location"]
    proof = client.get("/api/v1/settings/feishu/binding/proof").json()
    assert proof["consumed"]


def test_invalid_candidate_keeps_current_credential_and_binding(feishu_fixture):
    client, _, settings, headers = feishu_fixture
    configured, _ = bind(client, headers)
    with Session(client.app.state.engine) as db:
        original = dict(db.get(IntegrationState, "feishu").data)
    response = client.put(
        "/api/v1/settings/feishu",
        headers={**headers, "If-Match": f'"{configured["revision"]}"'},
        json={
            "app_id": "cli_synthetic",
            "app_secret": "invalid-candidate-secret",
            "enabled": True,
        },
    )
    assert response.status_code == 400, response.text
    with Session(client.app.state.engine) as db:
        actual = db.get(IntegrationState, "feishu")
        assert actual.revision == configured["revision"]
        assert actual.data == original
        assert (
            SecretBox(settings).decrypt(actual.data["secret"], "feishu") == "synthetic-app-secret"
        )


def test_wrong_tenant_and_changed_config_during_oauth_fail_closed(feishu_fixture):
    client, provider, _, headers = feishu_fixture
    bind(client, headers)
    provider["tenant"] = "another-tenant"
    started = client.get("/api/v1/auth/feishu/start", follow_redirects=False)
    raw = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    response = client.get(
        "/api/v1/auth/feishu/callback",
        params={"state": raw, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert "TENANT_MISMATCH" in response.headers["location"]
    provider["tenant"] = "tenant-test"

    def update():
        with Session(client.app.state.engine) as db:
            row = db.get(IntegrationState, "feishu")
            row.revision += 1
            db.commit()

    provider["on_oauth"] = update
    started = client.get("/api/v1/auth/feishu/start", follow_redirects=False)
    raw = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    response = client.get(
        "/api/v1/auth/feishu/callback",
        params={"state": raw, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert "CONFIG_CHANGED" in response.headers["location"]
    assert client.get("/api/v1/auth/me").json()["user"]["role"] == "admin"


def test_sso_callback_is_browser_bound_and_session_eligibility_expires(feishu_fixture):
    client, _, _, headers = feishu_fixture
    bind(client, headers)
    started = client.get(
        "/api/v1/auth/feishu/start", params={"return_to": "/apps/test"}, follow_redirects=False
    )
    raw = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    with TestClient(client.app) as foreign:
        foreign.get("/api/v1/auth/browser-context")
        invalid = foreign.get(
            "/api/v1/auth/feishu/callback",
            params={"state": raw, "code": "synthetic-code"},
            follow_redirects=False,
        )
        assert "OAUTH_STATE_INVALID" in invalid.headers["location"]
    valid = client.get(
        "/api/v1/auth/feishu/callback",
        params={"state": raw, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert valid.headers["location"] == "/apps/test"
    assert client.get("/api/v1/auth/me").json()["user"]["role"] == "downloader"
    with Session(client.app.state.engine) as db:
        row = db.scalar(select(AuthSession).where(AuthSession.kind == "feishu"))
        assert 0 < (row.eligibility_until - utcnow()).total_seconds() <= 28800
        row.eligibility_until = utcnow() - timedelta(seconds=1)
        db.commit()
    response = client.get("/api/v1/catalog/apps")
    assert response.status_code == 403


def prepare_delivery(client, settings):
    now = utcnow()
    with Session(client.app.state.engine) as db:
        db.add(
            IntegrationState(
                key="feishu",
                revision=1,
                data={
                    "app_id": "cli_synthetic",
                    "secret": SecretBox(settings).encrypt("synthetic-app-secret", "feishu"),
                    "tenant_key": "tenant-test",
                    "enabled": True,
                    "verified": True,
                },
            )
        )
        db.add(IntegrationState(key="bot", revision=1, data={"enabled": True, "verified": True}))
        db.add(
            ChatRecord(
                chat_id="chat-first",
                name="测试群",
                membership="joined",
                send_status="unverified",
                synced_at=now,
            )
        )
        db.flush()
        delivery = create_delivery(
            db,
            "chat-first",
            {
                "title": "测试",
                "summary": "通知测试",
                "app_name": None,
                "mode": "debug",
                "version_label": None,
                "file_names": [],
                "result": "test",
                "occurred_at": now.isoformat(),
                "page_url": None,
            },
        )
        identity = delivery.id
        db.commit()
        return identity


def test_delivery_mutex_prevents_duplicate_senders_and_unknown_false_positive(feishu_fixture):
    client, provider, settings, _ = feishu_fixture
    identity = prepare_delivery(client, settings)
    entered, finish = threading.Event(), threading.Event()

    def block():
        entered.set()
        assert finish.wait(timeout=10)

    provider["on_send"] = block

    def invoke():
        with Session(client.app.state.engine) as db:
            send_delivery(db, settings, identity)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(invoke)
        assert entered.wait(timeout=5)
        try:
            with pytest.raises(RetryLater):
                invoke()
            with Session(client.app.state.engine) as db:
                assert db.get(DeliveryRecord, identity).state == "sending"
        finally:
            finish.set()
        first.result(timeout=5)
    assert provider["sent"] == 1
    with Session(client.app.state.engine) as db:
        assert db.get(DeliveryRecord, identity).state == "succeeded"


def test_abandoned_send_is_unknown_and_retry_requires_ack(feishu_fixture):
    client, provider, settings, headers = feishu_fixture
    identity = prepare_delivery(client, settings)
    with Session(client.app.state.engine) as db:
        row = db.get(DeliveryRecord, identity)
        row.state = "sending"
        db.commit()
        send_delivery(db, settings, identity)
        assert row.state == "unknown"
    assert provider["sent"] == 0
    path = f"/api/v1/notifications/{identity}/retry"
    assert (
        client.post(path, headers={**headers, "Idempotency-Key": str(uuid4())}, json={}).status_code
        == 409
    )
    response = client.post(
        path,
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"acknowledge_possible_duplicate": True},
    )
    assert response.status_code == 202, response.text
    with Session(client.app.state.engine) as db:
        send_delivery(db, settings, identity)
        assert db.get(DeliveryRecord, identity).state == "succeeded"
        assert db.scalar(select(TaskRecord)) is not None
    assert provider["sent"] == 1


def test_bot_stale_verification_cannot_activate_new_configuration(feishu_fixture):
    client, provider, _, headers = feishu_fixture
    bind(client, headers)

    def update():
        with Session(client.app.state.engine) as db:
            row = db.get(IntegrationState, "feishu")
            row.revision += 1
            db.commit()

    provider["on_bot"] = update
    response = client.post("/api/v1/settings/feishu-bot/test", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFIG_CHANGED"
    assert not client.get("/api/v1/settings/feishu-bot").json()["verified"]


def test_complete_chat_search_and_test_message_has_one_parent_task(feishu_fixture):
    client, _, settings, headers = feishu_fixture
    bind(client, headers)
    response = client.post("/api/v1/settings/feishu-bot/test", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "partial"
    bot = client.get("/api/v1/settings/feishu-bot").json()
    response = client.put(
        "/api/v1/settings/feishu-bot",
        headers={**headers, "If-Match": f'"{bot["revision"]}"'},
        json={"enabled": True},
    )
    assert response.status_code == 200, response.text
    with Session(client.app.state.engine) as db:
        sync_chats(db, settings)
    response = client.get("/api/v1/settings/feishu-bot/chats", params={"q": "最后一页"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["chat_id"] == "chat-last"
    key = str(uuid4())
    payload = {"chat_ids": ["chat-first", "chat-last"]}
    response = client.post(
        "/api/v1/settings/feishu-bot/test-message",
        headers={**headers, "Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == 202, response.text
    repeated = client.post(
        "/api/v1/settings/feishu-bot/test-message",
        headers={**headers, "Idempotency-Key": key},
        json=payload,
    )
    assert repeated.json() == response.json()
    with Session(client.app.state.engine) as db:
        assert len(db.scalars(select(DeliveryRecord)).all()) == 2
        tasks = db.scalars(select(TaskRecord).where(TaskRecord.kind == "notification")).all()
        assert len(tasks) == 1
        assert len(tasks[0].payload["delivery_ids"]) == 2


def test_release_template_save_permissions_validation_and_snapshot(feishu_fixture):
    from app.domains.distribution.notification_templates import sample_card

    client, provider, _, headers = feishu_fixture
    from app.domains.applications.models import AppRecord

    with Session(client.app.state.engine) as db:
        apps = [
            AppRecord(
                name=name,
                public_slug=name,
                platforms=["android"],
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            for name in ("app-a", "app-b")
        ]
        db.add_all(apps)
        db.commit()
        app_id, other_id = (app.id for app in apps)
    path = f"/api/v1/apps/{app_id}/release-notification-template"
    other_path = f"/api/v1/apps/{other_id}/release-notification-template"
    initial = client.get(path)
    assert initial.status_code == 200
    assert initial.headers["etag"] == '"0"'
    with Session(client.app.state.engine) as db:
        default_card = create_delivery(
            db, "test-chat", sample_card(), app_id=app_id, kind="build_ready", enqueue_task=False
        ).card
        assert default_card["header_color"] == "green"
        assert "**Build**：2026100701" in default_card["summary"]
        db.rollback()
    draft = {**initial.json()["template"], "title": "{{app_name}} 上新", "button_text": "立即安装"}
    assert client.put(path, json=draft).status_code == 403
    assert client.put(path, json=draft, headers=headers).status_code == 422
    invalid = client.put(
        path, json={**draft, "body": "{{unknown}}"}, headers={**headers, "If-Match": '"0"'}
    )
    assert invalid.status_code == 422
    assert client.get(path).json()["revision"] == 0
    saved = client.put(path, json=draft, headers={**headers, "If-Match": '"0"'})
    assert saved.status_code == 200
    assert saved.headers["etag"] == '"1"'
    assert saved.json()["template"] == draft
    assert client.get(other_path).json()["revision"] == 0
    assert client.get(other_path).json()["template"]["title"] != draft["title"]
    assert saved.json()["sample"]["app_name"] == "app-a"
    assert saved.json()["sample"]["page_url"].endswith(f"/apps/{app_id}")
    malicious = client.put(
        path,
        json={**draft, "sub_button_url": "https://other.example"},
        headers={**headers, "If-Match": '"1"'},
    )
    assert malicious.status_code == 422
    assert client.get("/api/v1/settings/release-notification-template").status_code == 404
    with Session(client.app.state.engine) as db:
        delivery = create_delivery(
            db, "test-chat", sample_card(), app_id=app_id, kind="build_ready", enqueue_task=False
        )
        delivery_id = delivery.id
        first_card = dict(delivery.card)
        assert first_card["title"] == "SomeProject 上新"
        assert first_card["button_text"] == "立即安装"
        failed = create_delivery(
            db, "test-chat", sample_card(), kind="build_failed", enqueue_task=False
        )
        assert failed.card == sample_card()
        db.commit()
    assert client.put(path, json=draft, headers={**headers, "If-Match": '"0"'}).status_code == 412
    updated = client.put(
        path, json={**draft, "title": "新模板"}, headers={**headers, "If-Match": '"1"'}
    )
    assert updated.status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.get(DeliveryRecord, delivery_id).card == first_card
        assert (
            create_delivery(
                db,
                "test-chat",
                sample_card(),
                app_id=app_id,
                kind="build_ready",
                enqueue_task=False,
            ).card["title"]
            == "新模板"
        )
        # Never queue or send during template editing.
        assert not db.scalars(select(TaskRecord)).all()
    with Session(client.app.state.engine) as db:
        from app.domains.audit.models import AuditRecord

        edits = db.scalars(
            select(AuditRecord).where(AuditRecord.action == "notification_template.update")
        ).all()
        assert len(edits) == 2 and all(row.app_id == app_id for row in edits)
        other_card = create_delivery(
            db, "test-chat", sample_card(), app_id=other_id, kind="build_ready", enqueue_task=False
        ).card
        assert other_card["title"] != "新模板"
        app = db.get(AppRecord, app_id)
        app.archived_at = utcnow()
        db.commit()
    assert client.get(path).status_code == 200
    assert client.put(path, json=draft, headers={**headers, "If-Match": '"2"'}).status_code == 409
    assert provider["sent"] == 0
    client.cookies.clear()
    assert client.get(path).status_code == 401
