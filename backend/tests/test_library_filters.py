"""Administrator package provenance and visibility-preserving catalog filters."""

from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app
from test_package_import import source as source
from test_package_library import process

from app.domains.library.models import PackageRecord


def test_package_source_time_filters_and_admin_references(client, source):
    headers, app, _, _ = source
    upload = client.post(
        f"/api/v1/apps/{app['id']}/package-imports",
        headers=headers,
        json={"release_id": "70", "asset_id": "80", "mode": "release"},
    ).json()
    package_id = process(client, upload)
    with Session(client.app.state.engine) as db:
        created = db.get(PackageRecord, UUID(package_id)).created_at.isoformat()
    path = f"/api/v1/apps/{app['id']}/packages"
    assert client.get(path, params={"source_kind": "upload"}).json()["total"] == 0
    assert (
        client.get(path, params={"source_kind": "github", "created_from": created}).json()["total"]
        == 1
    )
    assert client.get(path, params={"created_before": created}).json()["total"] == 0
    assert (
        client.get(path, params={"created_from": created, "created_before": created}).status_code
        == 422
    )
    assert client.get(path, params={"created_from": "2026-10-04T00:00:00"}).status_code == 422
    version = client.post(
        f"/api/v1/apps/{app['id']}/versions",
        headers=headers,
        json={"display_name": "Release 2.0", "mode": "release", "release_notes": ""},
    ).json()
    publication = client.post(
        f"/api/v1/versions/{version['id']}/publications",
        headers=headers,
        json={"platform": "ios", "package_ids": [package_id]},
    ).json()
    detail = client.get(f"/api/v1/packages/{package_id}").json()
    assert detail["related_uploads"][0]["task_id"] == upload["task_id"]
    assert detail["publication_refs"][0]["id"] == publication["id"]
    assert detail["source_snapshot"]["repository"]["full_name"] == "example/mobile"
    client.cookies.clear()
    assert client.get(f"/api/v1/packages/{package_id}").status_code == 401


def test_catalog_name_filters_never_reveal_restricted_publications(client, source):
    headers, app, _, _ = source
    upload = client.post(
        f"/api/v1/apps/{app['id']}/package-imports",
        headers=headers,
        json={"release_id": "70", "asset_id": "80", "mode": "release"},
    ).json()
    package_id = process(client, upload)
    version = client.post(
        f"/api/v1/apps/{app['id']}/versions",
        headers=headers,
        json={"display_name": "Release 2.0", "mode": "release", "release_notes": ""},
    ).json()
    publication = client.post(
        f"/api/v1/versions/{version['id']}/publications",
        headers=headers,
        json={"platform": "ios", "package_ids": [package_id]},
    ).json()
    assert (
        client.post(
            f"/api/v1/publications/{publication['id']}/publish",
            headers={**headers, "If-Match": '"1"'},
        ).status_code
        == 200
    )
    path = "/api/v1/catalog/publications"
    filters = {"app_name": "M2", "version_name": "release 2"}
    admin_cookies = dict(client.cookies)
    client.cookies.clear()
    assert client.get(path, params=filters).json()["total"] == 0
    assert client.get(path, params={"app_id": app["id"]}).json()["total"] == 0
    assert client.get("/api/v1/catalog/publication-apps").json()["items"] == []
    client.cookies.update(admin_cookies)
    result = client.get(path, params=filters).json()
    assert result["total"] == 1
    assert client.get(path, params={"app_id": app["id"]}).json()["total"] == 1
    assert client.get(path, params={"app_id": str(uuid4())}).json()["total"] == 0
    assert "source_snapshot" not in str(result)
    assert client.get(path, params={**filters, "app_name": "other"}).json()["total"] == 0
    assert client.get(path, params={**filters, "version_name": "3.0"}).json()["total"] == 0


def test_publication_app_options_follow_catalog_visibility(client, configured_app):
    _, app = configured_app
    path = "/api/v1/catalog/publication-apps"
    # A qualified user can select an existing app before its first publication.
    assert client.get(path).json()["items"] == [{"id": app["id"], "name": app["name"]}]
    client.cookies.clear()
    assert client.get(path).json()["items"] == []
