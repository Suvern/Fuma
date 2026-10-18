"""App ownership is enforced at every management boundary, including totals and aliases."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import complete_first_login
from test_core_auth_apps import core_app as core_app
from test_m2_applications import ensure_ready_binding

from app.domains.audit.models import AuditRecord
from app.domains.auth.models import AppRoleRecord, AuthSession, User
from app.domains.auth.service import token_hash, utcnow
from app.domains.distribution.models import DeliveryRecord, TaskRecord
from app.domains.distribution.service import state
from app.domains.library.models import PackageRecord, PublicationRecord, UploadRecord, VersionRecord
from app.domains.storage.models import StorageLocation


@pytest.fixture
def managed_apps(client):
    headers = complete_first_login(client)
    apps = []
    for name in ("owned", "foreign"):
        result = client.post(
            "/api/v1/apps",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={
                "name": name,
                "public_slug": name,
                "platforms": ["ios"],
                "allowed_package_ids": [
                    {"platform": "ios", "mode": "debug", "identifier": "test.app"}
                ],
            },
        )
        assert result.status_code == 201, result.text
        apps.append(result.json())
    # Reuse a browser session with a seeded, verified Feishu identity. No provider calls.
    with Session(client.app.state.engine) as db:
        now = utcnow()
        config = state(db, "feishu")
        config.data = {"enabled": True, "verified": True, "app_id": "scope-app", "tenant_key": "t"}
        actor = User(
            kind="feishu",
            display_name="Scoped maintainer",
            open_id="maintainer",
            tenant_key="t",
            provider_app_id="scope-app",
            identity_verified_at=now,
            global_role="maintainer",
        )
        db.add(actor)
        db.flush()
        actor_id = actor.id
        db.add(AppRoleRecord(user_id=actor.id, app_id=UUID(apps[0]["id"])))
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == token_hash(client.cookies.get("fuma_session"))
            )
        )
        session.user_id, session.kind = actor.id, "feishu"
        session.feishu_config_revision = config.revision
        session.eligibility_until = now + timedelta(minutes=4)
        db.commit()
    return headers, apps, actor_id


def test_app_template_is_editable_only_with_current_app_permission(client, managed_apps):
    headers, apps, actor_id = managed_apps
    own, foreign = (f"/api/v1/apps/{row['id']}/release-notification-template" for row in apps)
    value = client.get(own)
    assert value.status_code == 200
    draft = {
        **value.json()["template"],
        "title": "仅当前应用",
        "sub_button_text": "下载 {{app_name}}",
    }
    saved = client.put(own, json=draft, headers={**headers, "If-Match": '"0"'})
    assert saved.status_code == 200, saved.text
    assert saved.json()["template"] == draft
    assert client.get(foreign).status_code == 404
    assert (
        client.put(foreign, json=draft, headers={**headers, "If-Match": '"0"'}).status_code == 404
    )
    with Session(client.app.state.engine) as db:
        actor = db.get(User, actor_id)
        actor.global_role = "downloader"
        db.commit()
    assert client.get(own).status_code == 403
    assert client.put(own, json=draft, headers={**headers, "If-Match": '"1"'}).status_code == 403


def test_app_scope_lists_writes_and_global_configuration(client, managed_apps):
    headers, apps, actor = managed_apps
    own, foreign = (row["id"] for row in apps)
    listed = client.get("/api/v1/apps", params={"page_size": 1}).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == own
    assert client.get("/api/v1/apps", params={"q": "foreign"}).json()["total"] == 0
    assert client.get(f"/api/v1/apps/{own}").status_code == 200
    assert client.get(f"/api/v1/apps/{foreign}").status_code == 404
    for suffix in (
        "packages",
        "uploads",
        "versions",
        "debug-entries",
        "actions-rules",
        "build-events",
        "github/releases",
        "release-defaults/ios",
        "distribution-statistics",
        "available-storage",
        "release-notification-template",
    ):
        assert client.get(f"/api/v1/apps/{foreign}/{suffix}").status_code == 404, suffix
    result = client.patch(
        f"/api/v1/apps/{own}", headers={**headers, "If-Match": '"1"'}, json={"name": "edited"}
    )
    assert result.status_code == 200, result.text
    assert (
        client.patch(
            f"/api/v1/apps/{foreign}", headers={**headers, "If-Match": '"1"'}, json={"name": "leak"}
        ).status_code
        == 404
    )
    for path in (
        "settings/storage-locations",
        "connectors/github",
        "settings/feishu",
        "settings/feishu-bot/chats",
    ):
        assert client.get(f"/api/v1/{path}").status_code == 403, path
    assert (
        client.post(
            "/api/v1/apps",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"name": "forbidden", "public_slug": "forbidden", "platforms": ["ios"]},
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/apps/{own}", headers={**headers, "If-Match": '"2"'}).status_code
        == 403
    )
    # Permission changes take effect without signing out or issuing another cookie.
    with Session(client.app.state.engine) as db:
        db.get(User, actor).global_role = "downloader"
        db.commit()
    assert client.get(f"/api/v1/apps/{own}").status_code == 403


def test_owned_resource_ids_cannot_bypass_app_scope(client, managed_apps):
    headers, apps, actor = managed_apps
    now = utcnow()
    with Session(client.app.state.engine) as db:
        foreign = UUID(apps[1]["id"])
        version = VersionRecord(
            app_id=foreign, display_name="hidden", mode="release", release_notes="", created_at=now
        )
        package = PackageRecord(
            app_id=foreign,
            platform="ios",
            mode="release",
            file_name="hidden.ipa",
            size_bytes=1,
            sha256="a" * 64,
            package_identifier="test.hidden",
            version_name="1",
            build_number="1",
            signature_status="unverified",
            parser_version="fixture",
            created_at=now,
        )
        upload = UploadRecord(
            app_id=foreign,
            actor_id=actor,
            file_name="hidden.ipa",
            declared_size=1,
            platform="ios",
            mode="release",
            chunk_size=1,
            expected_parts=1,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db.add_all([version, package, upload])
        db.flush()
        publication = PublicationRecord(
            app_id=foreign, version_id=version.id, platform="ios", mode="release", created_at=now
        )
        db.add(publication)
        db.flush()
        paths = [
            f"uploads/{upload.id}",
            f"packages/{package.id}",
            f"versions/{version.id}",
            f"publications/{publication.id}",
        ]
        package_id = package.id
        db.commit()
    for path in paths:
        assert client.get(f"/api/v1/{path}").status_code == 404, path
    assert (
        client.patch(
            f"/api/v1/packages/{package_id}",
            headers={**headers, "If-Match": '"1"'},
            json={"internal_notes": "forbidden"},
        ).status_code
        == 404
    )


def test_tasks_notifications_and_audit_filter_before_totals(client, managed_apps):
    headers, apps, actor = managed_apps
    now = utcnow()
    foreign_task = foreign_delivery = None
    with Session(client.app.state.engine) as db:
        for app_id in (UUID(apps[0]["id"]), UUID(apps[1]["id"]), None):
            task = TaskRecord(
                app_id=app_id, kind="release_sync", state="failed", created_at=now, updated_at=now
            )
            delivery = DeliveryRecord(
                app_id=app_id,
                chat_id="fixture",
                chat_name="target",
                kind="build_ready",
                state="failed",
                card={
                    "title": "fixture",
                    "summary": "fixture",
                    "app_name": None,
                    "mode": "debug",
                    "version_label": None,
                    "file_names": [],
                    "result": "success",
                    "occurred_at": now.isoformat(),
                    "page_url": None,
                },
                created_at=now,
                updated_at=now,
            )
            audit = AuditRecord(
                app_id=app_id,
                actor_kind="admin",
                action="scope.fixture",
                resource_type="app",
                outcome="success",
                request_id="fixture",
                summary="fixture",
                occurred_at=now,
            )
            db.add_all([task, delivery, audit])
            db.flush()
            if app_id == UUID(apps[1]["id"]):
                foreign_task, foreign_delivery = task.id, delivery.id
        db.commit()
    for path in ("tasks", "notifications"):
        result = client.get(f"/api/v1/{path}", params={"page_size": 1})
        assert result.status_code == 200, result.text
        assert result.json()["total"] == 1
        assert result.json()["items"][0]["app_id"] == apps[0]["id"]
        assert client.get(f"/api/v1/{path}", params={"app_id": apps[1]["id"]}).json()["total"] == 0
    assert (
        client.get("/api/v1/audit-events", params={"action": "scope.fixture"}).json()["total"] == 1
    )
    for path in (f"tasks/{foreign_task}", f"notifications/{foreign_delivery}"):
        assert client.get(f"/api/v1/{path}").status_code == 404
        assert client.post(f"/api/v1/{path}/retry", headers=headers, json={}).status_code == 404


def test_available_storage_is_verified_summary_only(client, managed_apps):
    _, apps, _ = managed_apps
    with Session(client.app.state.engine) as db:
        for status, enabled in [("ready", True), ("unverified", True), ("ready", False)]:
            db.add(
                StorageLocation(
                    name="configured",
                    provider="cos",
                    region="region",
                    bucket="bucket",
                    prefix="prefix",
                    read_mode="private",
                    encrypted_credentials="fixture-not-a-credential",
                    status=status,
                    enabled=enabled,
                )
            )
        db.commit()
    result = client.get(f"/api/v1/apps/{apps[0]['id']}/available-storage")
    assert result.status_code == 200, result.text
    items = result.json()["items"]
    assert len(items) == 1
    assert set(items[0]) == {"id", "name", "provider", "read_mode", "is_default"}


def test_retry_task_rebinds_current_authorized_actor(client, managed_apps):
    headers, apps, actor = managed_apps
    now = utcnow()
    with Session(client.app.state.engine) as db:
        previous = db.scalar(select(User).where(User.username == "admin"))
        row = TaskRecord(
            app_id=UUID(apps[0]["id"]),
            kind="release_sync",
            state="failed",
            created_actor_id=previous.id,
            actor_permission_revision=previous.permission_revision,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        task_id = row.id
        db.commit()
    result = client.post(
        f"/api/v1/tasks/{task_id}/retry",
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert result.status_code == 202, result.text
    with Session(client.app.state.engine) as db:
        row = db.get(TaskRecord, task_id)
        assert row.state == "queued" and row.created_actor_id == actor
        assert row.actor_permission_revision == db.get(User, actor).permission_revision


def test_upload_stream_revocation_rechecks_before_installing_part(client, managed_apps):
    import asyncio
    import hashlib
    from types import SimpleNamespace

    from app.api.library import upload_dir, upload_part
    from app.core.errors import AppError
    from app.domains.auth.service import AuthContext

    headers, apps, actor = managed_apps
    body = b"test"
    ensure_ready_binding(client, apps[0]["id"], "debug")
    result = client.post(
        f"/api/v1/apps/{apps[0]['id']}/uploads",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "file_name": "test.ipa",
            "declared_size": len(body),
            "platform": "ios",
            "mode": "debug",
        },
    )
    assert result.status_code == 201, result.text
    upload_id = UUID(result.json()["id"])

    async def stream():
        # The snapshot transaction has ended before HTTP bytes arrive. A real
        # separate database transaction revokes this uploader during transfer.
        with Session(client.app.state.engine) as revoke:
            revoke.get(User, actor).global_role = "downloader"
            revoke.commit()
        yield body

    request = SimpleNamespace(app=client.app, stream=stream)
    with Session(client.app.state.engine) as db:
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == actor))
        context = AuthContext(session=session, user=db.get(User, actor))
        with pytest.raises(AppError, match="后台管理权限"):
            asyncio.run(
                upload_part(
                    upload_id, 1, request, db, context, context, hashlib.sha256(body).hexdigest()
                )
            )
        db.rollback()
        assert db.get(UploadRecord, upload_id).parts == []
    assert list(upload_dir(client.app.state.settings, upload_id).iterdir()) == []


@pytest.mark.parametrize("kind", ["notification", "release_import"])
def test_worker_provider_read_allows_revocation_and_rechecks_before_write(
    client, managed_apps, monkeypatch, kind
):
    from sqlalchemy import text

    from app.domains.applications.models import AppRecord
    from app.workers.tasks import execute_task

    _, apps, actor = managed_apps
    app_id = UUID(apps[0]["id"])
    now = utcnow()
    binding = {"connector_id": str(uuid4()), "repository_id": "1", "full_name": "fixture/app"}
    with Session(client.app.state.engine) as db:
        db.get(AppRecord, app_id).repository = binding
        delivery = DeliveryRecord(
            app_id=app_id,
            chat_id="fixture",
            chat_name="fixture",
            kind="test",
            state="queued",
            card={},
            created_at=now,
            updated_at=now,
        )
        db.add(delivery)
        db.flush()
        delivery_id = delivery.id
        task = TaskRecord(
            app_id=app_id,
            kind=kind,
            created_actor_id=actor,
            actor_permission_revision=1,
            resource_id=str(delivery_id) if kind == "notification" else str(app_id),
            payload={
                "binding": binding,
                "matches": [
                    {
                        "release_id": "1",
                        "asset_id": "2",
                        "tag_name": "v1",
                        "source": {
                            "repository_id": "1",
                            "release_id": "1",
                            "asset_id": "2",
                            "asset_updated_at": now.isoformat(),
                            "size_bytes": 4,
                        },
                    }
                ],
            },
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.flush()
        task_id = task.id
        db.commit()
    observed = []

    def revoke():
        # A separate transaction must not be blocked by provider preparation.
        # A lock timeout makes a regression fail promptly rather than hang CI.
        with Session(client.app.state.engine) as other:
            other.execute(text("SET LOCAL lock_timeout = '500ms'"))
            user = other.get(User, actor)
            user.global_role = "downloader"
            user.permission_revision += 1
            other.commit()
        observed.append("revoked")

    class Provider:
        def tenant_token(self):
            revoke()

        def send_card(self, *args):
            observed.append("sent")
            return "unexpected"

        def close(self):
            pass

    def fetch(*args):
        revoke()
        return binding, {}, []

    monkeypatch.setattr("app.domains.distribution.feishu.bot_client", lambda *args: Provider())
    monkeypatch.setattr("app.domains.distribution.packages.fetch_import_source", fetch)
    execute_task(client.app.state.engine, client.app.state.settings, task_id)
    assert observed == ["revoked"]
    with Session(client.app.state.engine) as db:
        task = db.get(TaskRecord, task_id)
        assert task.state == "failed" and task.error_code == "TASK_AUTHORIZATION_REVOKED"
        assert db.scalar(
            select(AuditRecord).where(AuditRecord.action == "task.authorization_revoked")
        )
        if kind == "notification":
            assert db.get(DeliveryRecord, delivery_id).state == "failed"
