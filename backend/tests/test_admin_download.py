"""Administrator sessions share the download portal without Feishu credentials."""

from datetime import timedelta
from http.cookies import SimpleCookie

import pytest
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_distribution_review import download_fixture as download_fixture
from test_distribution_review import grant_request

from app.domains.auth.models import AuthSession, User
from app.domains.auth.service import create_user_session, utcnow
from app.domains.distribution.models import DebugRecord
from app.domains.distribution.service import state


def admin_session(client, settings, condition=None):
    with Session(client.app.state.engine) as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        user.must_change_password = condition == "initial_password"
        user.active = condition != "disabled"
        if condition == "other_local_user":
            user.username = "not-admin"
        response = Response()
        session, csrf = create_user_session(db, response, user, settings)
        if condition == "expired":
            session.expires_at = utcnow() - timedelta(seconds=1)
        if condition == "revoked":
            session.revoked_at = utcnow()
        # Administrator downloads must work even when Feishu has not been set up.
        state(db, "feishu").data = {}
        db.commit()
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    client.cookies.set("fuma_session", cookie["fuma_session"].value)
    return csrf


def test_admin_catalog_and_download_without_feishu(download_fixture):
    client, entry_id, _, settings = download_fixture
    csrf = admin_session(client, settings)
    assert client.get("/api/v1/auth/browser-context").json()["eligibility_expires_at"] is None
    assert client.get("/api/v1/catalog/apps").json()["total"] == 1
    assert client.get(f"/api/v1/catalog/debug-entries/{entry_id}").status_code == 200
    assert client.get(f"/api/v1/catalog/debug-entries/{entry_id}/preparation").status_code == 200
    grant = grant_request(client, entry_id, csrf)
    assert grant.status_code == 200, grant.text
    assert client.get(grant.json()["download_url"]).content == b"0123456789"
    with Session(client.app.state.engine) as db:
        entry = db.get(DebugRecord, entry_id)
        entry.enabled = False
        db.commit()
    assert grant_request(client, entry_id, csrf).status_code == 404


@pytest.mark.parametrize(
    "condition", ["initial_password", "disabled", "expired", "revoked", "other_local_user"]
)
def test_invalid_admin_session_cannot_download(download_fixture, condition):
    client, entry_id, _, settings = download_fixture
    csrf = admin_session(client, settings, condition)
    assert client.get("/api/v1/catalog/apps").status_code in (401, 403)
    assert grant_request(client, entry_id, csrf).status_code in (401, 403)


def test_admin_grant_rechecks_revocation(download_fixture, monkeypatch):
    from app.api import packages

    client, entry_id, _, settings = download_fixture
    csrf = admin_session(client, settings)
    original = packages.idem_begin

    def revoke_before_grant(db, *args):
        result = original(db, *args)
        for session in db.scalars(select(AuthSession).where(AuthSession.kind == "local")):
            session.revoked_at = utcnow()
        db.flush()
        return result

    monkeypatch.setattr(packages, "idem_begin", revoke_before_grant)
    assert grant_request(client, entry_id, csrf).status_code == 403
