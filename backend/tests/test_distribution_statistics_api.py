"""Statistics integration: UTC windowing, atomic accumulation and unknown legacy dates."""

from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_library_management import package
from test_m2_applications import configured_app as configured_app

from app.domains.auth.service import utcnow
from app.domains.distribution.statistics import COUNTERS, record_observation
from app.domains.library.models import LibraryGrant


def test_statistics_window_counts_and_access(client, configured_app, storage_cloud, monkeypatch):
    headers, app, package_id = package(client, configured_app, monkeypatch)
    version = client.post(
        f"/api/v1/apps/{app['id']}/versions",
        headers=headers,
        json={"display_name": "stats", "mode": "release", "release_notes": ""},
    ).json()
    publication = client.post(
        f"/api/v1/versions/{version['id']}/publications",
        headers=headers,
        json={"platform": "ios", "package_ids": [package_id]},
    ).json()
    today = utcnow().date()
    midnight = datetime.combine(today, time.min, tzinfo=UTC)
    with Session(client.app.state.engine) as db:
        rows = [
            LibraryGrant(
                token_hash=str(index) * 64,
                publication_id=UUID(publication["id"]),
                package_id=UUID(package_id),
                expires_at=utcnow() + timedelta(minutes=5),
                created_at=created,
            )
            for index, created in enumerate(
                [midnight, midnight - timedelta(microseconds=1), midnight]
            )
        ]
        db.add_all(rows)
        db.flush()
        rows[2].created_at = None  # Existing migration rows have an unknown issuance timestamp.
        db.commit()
    values = dict.fromkeys(COUNTERS, 0) | {
        "local_get_requests": 1,
        "partial_get_requests": 1,
        "observed_bytes": 123,
    }
    for _ in range(2):
        record_observation(client.app.state.engine, UUID(app["id"]), today, values)
    url = f"/api/v1/apps/{app['id']}/distribution-statistics"
    result = client.get(url, params={"start_date": str(today), "end_date": str(today)})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["totals"]["grant_count"] == 1
    assert data["totals"]["local_get_requests"] == 2
    assert data["totals"]["observed_bytes"] == 246
    assert len(data["days"]) == 1 and data["days"][0]["date"] == str(today)
    assert (
        client.get(url, params={"start_date": str(today - timedelta(days=90))}).status_code == 422
    )
    assert client.get(url, params={"end_date": str(today + timedelta(days=1))}).status_code == 422
    assert client.get(url, params={"end_date": "0001-01-01"}).status_code == 200
    assert client.get(f"/api/v1/apps/{uuid4()}/distribution-statistics").status_code == 404
    client.cookies.clear()
    assert client.get(url).status_code == 401
