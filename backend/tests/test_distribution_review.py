"""Independent regression coverage for distribution authorization and cache invariants."""

import base64
import hashlib
import secrets
from datetime import timedelta
from http.cookies import SimpleCookie
from uuid import uuid4

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.packages import router
from app.core.config import Settings
from app.domains.applications.models import AppRecord
from app.domains.auth.models import User
from app.domains.auth.service import create_user_session, utcnow
from app.domains.distribution.models import DebugRecord, GrantRecord, IntegrationState
from app.domains.distribution.packages import cache_path, cleanup_cache, ensure_cache
from app.domains.distribution.service import state
from app.infrastructure.database import Base, build_engine
from app.main import create_app


@pytest.fixture
def download_fixture(tmp_path, isolated_database_url):
    settings = Settings(
        database_url=isolated_database_url,
        encryption_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        cache_dir=tmp_path,
        state_dir=tmp_path / "state",
    )
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    payload, now = b"0123456789", utcnow()
    with Session(engine) as db:
        from app.domains.system.models import SystemState

        db.add(SystemState(id=1))
        app = AppRecord(
            name="Test App",
            public_slug="test-app",
            description="",
            platforms=["android"],
            enabled=True,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        user = User(
            kind="feishu",
            tenant_key="tenant-test",
            open_id="test-member",
            display_name="测试成员",
            provider_app_id="synthetic-app",
            identity_verified_at=now,
        )
        db.add_all([app, user])
        db.flush()
        row = DebugRecord(
            app_id=app.id,
            connector_id=uuid4(),
            source_identity="a" * 64,
            source={
                "repository_id": "1",
                "repository_full_name": "owner/private",
                "release_id": "2",
                "asset_id": "3",
                "asset_updated_at": now.isoformat(),
                "size_bytes": len(payload),
                "digest": None,
            },
            platform="android",
            file_name="debug.apk",
            size_bytes=len(payload),
            source_tag="v1",
            enabled=True,
            revision=1,
            cache_state="ready",
            downloaded_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            last_access_at=now,
            cache_updated_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        db.add(
            IntegrationState(
                key="feishu",
                revision=1,
                data={
                    "enabled": True,
                    "verified": True,
                    "tenant_key": "tenant-test",
                    "app_id": "synthetic-app",
                },
            )
        )
        response = Response()
        _, csrf = create_user_session(
            db,
            response,
            user,
            settings,
            eligibility_until=now + timedelta(seconds=300),
            config_revision=1,
        )
        cookie = SimpleCookie()
        cookie.load(response.headers["set-cookie"])
        entry_id = row.id
        cache_path(settings, row).write_bytes(payload)
        db.commit()
    app = create_app(settings)
    if not any(
        getattr(route, "path", "") == "/api/v1/downloads/{opaque_token}" for route in app.routes
    ):
        app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("fuma_session", cookie["fuma_session"].value)
        yield client, entry_id, csrf, settings
    engine.dispose()


def grant_request(client, entry_id, csrf):
    return client.post(
        f"/api/v1/catalog/debug-entries/{entry_id}/download-grants",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": str(uuid4()),
        },
    )


def test_download_grant_range_head_expiry_and_cleanup_lease(download_fixture):
    client, identity, csrf, settings = download_fixture
    response = grant_request(client, identity, csrf)
    assert response.status_code == 200, response.text
    url = response.json()["download_url"]
    response = client.get(url, headers={"Range": "bytes=2-5"})
    assert response.status_code == 206, response.text
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"
    assert client.head(url, headers={"Range": "bytes=2-5"}).headers["content-length"] == "10"
    assert client.head(url).content == b""
    rejected = client.get(url, headers={"Range": "bytes=20-30"})
    assert rejected.status_code == 416
    assert rejected.headers["content-range"] == "bytes */10"
    with Session(client.app.state.engine) as db:
        cleanup_cache(db, settings, "all_unleased")
        entry = db.get(DebugRecord, identity)
        assert entry.cache_state == "ready"
        assert cache_path(settings, entry).exists()
        for grant in db.scalars(select(GrantRecord)):
            grant.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get(url).status_code == 410
    assert client.head(url).status_code == 410
    assert client.head(url).content == b""


def test_waiting_grant_rechecks_entry_disable(download_fixture, monkeypatch):
    client, identity, csrf, _ = download_fixture
    from app.api import packages

    original = packages.lock
    disabled = False

    def interleaving(db, key):
        nonlocal disabled
        if key == "cache_source:" + "a" * 64 and not disabled:
            with Session(client.app.state.engine) as other:
                row = other.get(DebugRecord, identity)
                row.enabled = False
                other.commit()
            disabled = True
        return original(db, key)

    monkeypatch.setattr(packages, "lock", interleaving)
    response = grant_request(client, identity, csrf)
    assert response.status_code == 404, response.text
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(GrantRecord)) is None


def test_cache_prepare_keeps_running_reservation(download_fixture):
    client, identity, _, _ = download_fixture
    with Session(client.app.state.engine) as db:
        row = db.get(DebugRecord, identity)
        row.cache_state, row.downloaded_bytes = "downloading", 5
        row.cache_record.cache_state, row.cache_record.downloaded_bytes = "downloading", 5
        db.commit()
        ensure_cache(db, row)
        db.commit()
        assert row.cache_state == "downloading"
        assert row.downloaded_bytes == 5


def test_cache_eviction_preserves_first_content_digest(download_fixture):
    client, identity, _, settings = download_fixture
    with Session(client.app.state.engine) as db:
        row = db.get(DebugRecord, identity)
        checksum = row.sha256
        cleanup_cache(db, settings, "all_unleased")
        db.refresh(row)
        assert row.cache_state == "evicted"
        assert not cache_path(settings, row).exists()
        assert row.sha256 == checksum


def test_locked_state_refreshes_revision_after_external_change(download_fixture):
    client, _, _, _ = download_fixture
    with Session(client.app.state.engine) as first:
        prior = state(first, "feishu")
        with Session(client.app.state.engine) as second:
            actual = second.get(IntegrationState, "feishu")
            actual.revision += 1
            second.commit()
        assert state(first, "feishu", locked=True).revision == 2
        assert prior.revision == 2
