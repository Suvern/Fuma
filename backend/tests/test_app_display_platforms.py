"""Platform pause preserves historical records and stops new authorization."""

import base64
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app
from test_m2_applications import patch

from app.api.packages import visible_entry
from app.core.errors import AppError
from app.domains.applications.models import AppRecord
from app.domains.applications.service import platform_enabled, require_platform_enabled
from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord
from app.domains.distribution.packages import catalog_app
from app.domains.library.models import PackageRecord, PublicationRecord, VersionRecord


def test_icon_validation_and_omission_preserves_value(client, configured_app):
    headers, app = configured_app
    valid = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nicon").decode()
    for invalid in [
        "https://tracker.test/icon.png",
        "data:image/svg+xml;base64,PHN2Zz4=",
        "data:image/png;base64,bm90LXBuZw==",
        "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 65536).decode(),
    ]:
        assert patch(client, headers, app, {"icon_data": invalid}).status_code == 422
    saved = patch(client, headers, app, {"icon_data": valid}).json()
    assert saved["icon_data"] == valid
    renamed = patch(client, headers, saved, {"name": "新名字"}).json()
    assert renamed["icon_data"] == valid
    assert patch(client, headers, renamed, {"icon_data": ""}).json()["icon_data"] == ""


def test_platform_pause_keeps_history_and_filters_new_authorization(client, configured_app):
    headers, app = configured_app
    with Session(client.app.state.engine) as db:
        entry = DebugRecord(
            app_id=UUID(app["id"]),
            connector_id=uuid4(),
            source_identity="7" * 64,
            platform="android",
            file_name="old.apk",
            size_bytes=10,
            source_tag="v1",
            source={"legacy": True},
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(entry)
        db.commit()
        entry_id = entry.id
    paused = patch(client, headers, app, {"disabled_platforms": ["android"]}).json()
    assert paused["platforms"] == ["android", "ios"]
    assert paused["debug_entry_count"] == 1
    assert paused["allowed_package_ids"] == app["allowed_package_ids"]
    with Session(client.app.state.engine) as db:
        record = db.get(AppRecord, UUID(app["id"]))
        assert not platform_enabled(record, "android")
        assert platform_enabled(record, "ios")
        assert catalog_app(db, record)["debug_entry_count"] == 0
        assert catalog_app(db, record)["platforms"] == ["ios"]
        with pytest.raises(AppError):
            visible_entry(db, entry_id)
        with pytest.raises(AppError):
            require_platform_enabled(record, "android")
        assert db.get(DebugRecord, entry_id).source == {"legacy": True}
    assert patch(client, headers, paused, {"disabled_platforms": ["ios", "ios"]}).status_code == 422
    resumed = patch(client, headers, paused, {"disabled_platforms": []})
    assert resumed.status_code == 200
    with Session(client.app.state.engine) as db:
        assert visible_entry(db, entry_id).id == entry_id


def test_public_copies_block_pause_and_counts_include_history(client, configured_app):
    headers, app = configured_app
    with Session(client.app.state.engine) as db:
        version = VersionRecord(
            app_id=UUID(app["id"]),
            display_name="v1",
            mode="release",
            release_notes="",
            created_at=utcnow(),
        )
        db.add(version)
        db.flush()
        publication = PublicationRecord(
            app_id=version.app_id,
            version_id=version.id,
            platform="android",
            mode="release",
            state="unpublished",
            access_state="reclaim_failed",
            created_at=utcnow(),
        )
        db.add(publication)
        for index, state in enumerate(["ready", "deleted"]):
            db.add(
                PackageRecord(
                    app_id=version.app_id,
                    platform="android",
                    mode="release",
                    file_name="app.apk",
                    size_bytes=10,
                    sha256=str(index) * 64,
                    package_identifier="com.test.app",
                    version_name="1",
                    build_number=str(index),
                    signature_status="verified",
                    parser_version="test",
                    state=state,
                    created_at=utcnow(),
                )
            )
        db.commit()
        publication_id = publication.id
    result = client.get(f"/api/v1/apps/{app['id']}").json()
    assert result["package_count"] == 1 and result["publication_count"] == 1
    assert patch(client, headers, app, {"disabled_platforms": ["android"]}).status_code == 409
    assert patch(client, headers, app, {"enabled": False}).status_code == 409
    with Session(client.app.state.engine) as db:
        db.get(PublicationRecord, publication_id).access_state = "reclaimed"
        db.commit()
    assert patch(client, headers, app, {"disabled_platforms": ["android"]}).status_code == 200
