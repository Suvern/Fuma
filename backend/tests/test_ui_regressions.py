"""UI-facing search and chronology regressions on disposable PostgreSQL."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import complete_first_login
from test_core_auth_apps import core_app as core_app
from test_distribution_review import download_fixture as download_fixture

from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord, TaskRecord
from app.domains.distribution.packages import sort_entries


def test_task_search_matches_visible_names_and_combined_filters(client):
    complete_first_login(client)
    now = utcnow()
    with Session(client.app.state.engine) as db:
        for kind, state in [
            ("cache_cleanup", "succeeded"),
            ("cache_cleanup", "failed"),
            ("release_sync", "succeeded"),
        ]:
            db.add(
                TaskRecord(
                    kind=kind,
                    state=state,
                    phase="done",
                    resource_id="resource-42",
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()
    for keyword in ["缓存清理", "缓存", "cache_cleanup", " 缓存清理 "]:
        result = client.get("/api/v1/tasks", params={"q": keyword})
        assert result.status_code == 200
        assert result.json()["total"] == 2
    result = client.get(
        "/api/v1/tasks",
        params={
            "q": "resource-42",
            "kind": "cache_cleanup",
            "state": "failed",
            "page_size": 1,
        },
    ).json()
    assert result["total"] == 1
    assert result["items"][0]["state"] == "failed"
    assert client.get("/api/v1/tasks", params={"kind": "invalid"}).status_code == 422


def entry(app_id, identity, imported, source_time):
    return DebugRecord(
        id=UUID(int=identity),
        app_id=app_id,
        connector_id=uuid4(),
        source_identity=f"{identity:064x}",
        platform="android",
        file_name=f"{identity}.apk",
        size_bytes=10,
        source_tag="v1",
        enabled=True,
        created_at=imported,
        updated_at=imported,
        source={
            "repository_id": "1",
            "repository_full_name": "test/app",
            "release_id": "2",
            "asset_id": str(identity),
            "asset_updated_at": source_time,
            "size_bytes": 10,
            "digest": None,
        },
    )


def test_admin_sort_is_source_based_stable_and_before_pagination(client):
    headers = complete_first_login(client)
    app = client.post(
        "/api/v1/apps",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"name": "排序测试", "public_slug": "sort-test", "platforms": ["android"]},
    )
    assert app.status_code == 201
    app_id = app.json()["id"]
    now = utcnow()
    with Session(client.app.state.engine) as db:
        db.add_all(
            [
                entry(UUID(app_id), 1, now, (now - timedelta(days=3)).isoformat()),
                entry(UUID(app_id), 2, now - timedelta(days=1), now.isoformat()),
                entry(UUID(app_id), 3, now - timedelta(days=2), now.isoformat()),
            ]
        )
        db.commit()
    path = f"/api/v1/apps/{app_id}/debug-entries"
    ids = []
    for page in [1, 2, 3]:
        result = client.get(path, params={"page_size": 1, "page": page}).json()
        assert result["total"] == 3
        ids.append(result["items"][0]["id"])
    assert ids == [str(UUID(int=n)) for n in [3, 2, 1]]
    imported = client.get(path, params={"sort": "imported_at"}).json()
    assert [item["id"] for item in imported["items"]] == [str(UUID(int=n)) for n in [1, 2, 3]]
    assert client.get(path, params={"sort": "invalid"}).status_code == 422
    assert client.get(path, params={"q": "1.apk", "page_size": 1}).json()["total"] == 1


def test_catalog_uses_same_order_and_exposes_only_source_time(download_fixture):
    client, identity, _, _ = download_fixture
    with Session(client.app.state.engine) as db:
        existing = db.get(DebugRecord, identity)
        now = existing.created_at
        existing.source = {
            **existing.source,
            "asset_updated_at": (now - timedelta(days=3)).isoformat(),
        }
        db.add(entry(existing.app_id, 2, now - timedelta(days=1), now.isoformat()))
        db.commit()
    response = client.get("/api/v1/catalog/debug-entries")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["id"] == str(UUID(int=2))
    assert items[0]["source_updated_at"] is not None
    assert "source" not in items[0]
    assert client.get("/api/v1/catalog/debug-entries", params={"sort": "imported_at"}).json()[
        "items"
    ][0]["id"] == str(identity)


def test_source_sort_handles_legacy_missing_time_and_timezones():
    now = utcnow()
    fallback = entry(uuid4(), 1, now, None)
    older = entry(
        fallback.app_id, 2, now + timedelta(days=1), (now - timedelta(days=1)).isoformat()
    )
    assert sort_entries([older, fallback]) == [fallback, older]
    fallback.source["asset_updated_at"] = "invalid legacy value"
    assert sort_entries([older, fallback]) == [fallback, older]
    fallback.source["asset_updated_at"] = "2026-10-04T16:00:00+08:00"
    older.source["asset_updated_at"] = "2026-10-04T09:00:00Z"
    assert sort_entries([fallback, older]) == [older, fallback]
