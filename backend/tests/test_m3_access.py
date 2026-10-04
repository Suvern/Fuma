"""Roles are current database authority, independent of browser cookie age."""

from datetime import timedelta
from http.cookies import SimpleCookie
from uuid import UUID

import pytest
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import core_app as core_app
from test_m2_applications import configured_app as configured_app

from app.core.errors import AppError
from app.domains.access.authorization import require_actor_permission, require_app_permission
from app.domains.auth.models import AuthSession, RoleChangeRecord, User
from app.domains.auth.service import AuthContext, cookie_name, create_user_session, utcnow
from app.domains.distribution.service import state


@pytest.fixture
def member(client, configured_app):
    headers, app = configured_app
    with Session(client.app.state.engine) as db:
        config = state(db, "feishu", locked=True)
        config.data = {
            "app_id": "provider-current",
            "tenant_key": "tenant",
            "verified": True,
            "enabled": True,
        }
        config.revision = 1
        user = User(
            kind="feishu",
            display_name="团队成员",
            tenant_key="tenant",
            open_id="member-one",
            provider_app_id="provider-current",
            identity_verified_at=utcnow(),
        )
        db.add(user)
        db.commit()
        user_id = user.id
    return headers, app, user_id


def assign(client, headers, user_id, role, apps=(), *, active=True, revision=1):
    return client.put(
        f"/api/v1/settings/members/{user_id}/roles",
        headers={**headers, "If-Match": f'"{revision}"'},
        json={"role": role, "managed_app_ids": list(apps), "active": active},
    )


def login_member(client, user_id):
    response = Response()
    with Session(client.app.state.engine) as db:
        user = db.get(User, user_id)
        session, csrf = create_user_session(
            db,
            response,
            user,
            client.app.state.settings,
            eligibility_until=utcnow() + timedelta(seconds=300),
            config_revision=1,
        )
        session_id = session.id
        db.commit()
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    name = cookie_name(client.app.state.settings)
    client.cookies.clear()
    client.cookies.set(name, cookies[name].value)
    return {"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf}, session_id


def test_role_update_is_current_scoped_revisioned_and_audited(client, member):
    headers, app, user_id = member
    before = client.get("/api/v1/settings/members", params={"q": "团队成员"}).json()
    assert before["total"] == 1 and before["items"][0]["role"] == "downloader"
    assert assign(client, headers, user_id, "maintainer").status_code == 422
    result = assign(client, headers, user_id, "maintainer", [app["id"]])
    assert result.status_code == 200, result.text
    assert result.json()["permission_revision"] == 2
    audit = client.get("/api/v1/audit-events", params={"action": "member.roles_updated"})
    assert audit.status_code == 200, audit.text
    assert audit.json()["items"][0]["actor_kind"] == "admin"
    assert assign(client, headers, user_id, "downloader").status_code == 412
    assert (
        client.get(
            "/api/v1/settings/members", params={"role": "maintainer", "app_id": app["id"]}
        ).json()["total"]
        == 1
    )
    with Session(client.app.state.engine) as db:
        change = db.scalar(select(RoleChangeRecord).where(RoleChangeRecord.user_id == user_id))
        assert change.before_rules["role"] == "downloader"
        assert change.after_rules["managed_app_ids"] == [app["id"]]
    old_admin_cookies = dict(client.cookies)
    _, session_id = login_member(client, user_id)
    session = client.get("/api/v1/auth/me").json()
    assert session["user"]["role"] == "maintainer"
    assert session["user"]["managed_app_ids"] == [app["id"]]
    assert client.get("/api/v1/settings/members").status_code == 403
    assert client.get("/api/v1/settings/storage-locations").status_code == 403
    with Session(client.app.state.engine) as db:
        context = AuthContext(db.get(AuthSession, session_id), db.get(User, user_id))
        assert require_app_permission(db, context, app["id"], lock=True).id == UUID(app["id"])
        assert db.info["actor_user_id"] == user_id
        db.rollback()
    member_cookies = dict(client.cookies)
    client.cookies.clear()
    client.cookies.update(old_admin_cookies)
    assert assign(client, headers, user_id, "downloader", revision=2).status_code == 200
    client.cookies.clear()
    client.cookies.update(member_cookies)
    assert client.get("/api/v1/auth/me").json()["user"]["role"] == "downloader"
    with Session(client.app.state.engine) as db:
        with pytest.raises(AppError):
            require_actor_permission(db, user_id, app["id"])


def test_local_rescue_and_provider_identity_cannot_be_reauthorized(client, member):
    headers, app, user_id = member
    local_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    assert assign(client, headers, local_id, "downloader", active=False).status_code == 409
    with Session(client.app.state.engine) as db:
        user = db.get(User, user_id)
        user.provider_app_id = "provider-old"
        db.commit()
    assert assign(client, headers, user_id, "admin").status_code == 409
    assert assign(client, headers, user_id, "maintainer", [app["id"]]).status_code == 409
    # A same-name/open-id identity from a different App is a separate record.
    with Session(client.app.state.engine) as db:
        current = User(
            kind="feishu",
            display_name="团队成员",
            tenant_key="tenant",
            open_id="member-one",
            provider_app_id="provider-current",
            identity_verified_at=utcnow(),
        )
        db.add(current)
        db.commit()
        assert current.id != user_id and current.global_role == "downloader"


def test_global_feishu_admin_and_disabled_account_boundaries(client, member):
    headers, _, user_id = member
    assert assign(client, headers, user_id, "admin").status_code == 200
    admin_cookies = dict(client.cookies)
    _, session_id = login_member(client, user_id)
    assert client.get("/api/v1/settings/members").status_code == 200
    assert client.get("/api/v1/settings/storage-locations").status_code == 200
    # Long jobs depend on current identity and scope, not the initiating browser TTL.
    with Session(client.app.state.engine) as db:
        session = db.get(AuthSession, session_id)
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        assert require_actor_permission(db, user_id, None).id == user_id
        db.rollback()
    member_cookies = dict(client.cookies)
    client.cookies.clear()
    client.cookies.update(admin_cookies)
    assert assign(client, headers, user_id, "admin", active=False, revision=2).status_code == 200
    client.cookies.clear()
    client.cookies.update(member_cookies)
    assert client.get("/api/v1/auth/me").status_code == 401
    with Session(client.app.state.engine) as db:
        assert db.get(AuthSession, session_id).revoked_at is not None
        with pytest.raises(AppError):
            require_actor_permission(db, user_id, None)


def test_provider_change_revokes_old_identity_without_reusing_roles(client, member):
    headers, _, user_id = member
    assert assign(client, headers, user_id, "admin").status_code == 200
    rescue_cookies = dict(client.cookies)
    login_member(client, user_id)
    assert client.get("/api/v1/settings/members").status_code == 200
    with Session(client.app.state.engine) as db:
        config = state(db, "feishu", locked=True)
        config.data = {**config.data, "app_id": "provider-new"}
        config.revision += 1
        db.commit()
    assert client.get("/api/v1/auth/me").json()["user"]["role"] == "downloader"
    assert client.get("/api/v1/settings/members").status_code == 403
    with Session(client.app.state.engine) as db:
        with pytest.raises(AppError):
            require_actor_permission(db, user_id, None)
    client.cookies.clear()
    client.cookies.update(rescue_cookies)
    assert assign(client, headers, user_id, "admin", active=False, revision=2).status_code == 200


def test_write_authority_fence_serializes_role_revocation(client, member):
    from sqlalchemy.exc import DBAPIError

    headers, app, user_id = member
    assert assign(client, headers, user_id, "maintainer", [app["id"]]).status_code == 200
    with Session(client.app.state.engine) as operation:
        require_actor_permission(operation, user_id, app["id"], lock=True)
        with Session(client.app.state.engine) as revocation:
            revocation.connection().exec_driver_sql("SET LOCAL lock_timeout = '100ms'")
            with pytest.raises(DBAPIError):
                state(revocation, "feishu", locked=True)
            revocation.rollback()
        operation.rollback()
    assert assign(client, headers, user_id, "downloader", revision=2).status_code == 200
    with Session(client.app.state.engine) as operation:
        with pytest.raises(AppError):
            require_actor_permission(operation, user_id, app["id"], lock=True)


def test_roles_upgrade_preserves_accounts_and_only_binds_proven_provider(core_app):
    import importlib.util
    from pathlib import Path
    from uuid import uuid4

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    from app.infrastructure.database import Base

    def migration(path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    directory = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    schema = "m3_identity_upgrade_" + uuid4().hex
    ids = {name: uuid4() for name in ("local", "proven", "stale", "foreign")}
    with core_app.state.test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
        with Operations.context(context):
            for path in sorted(directory.glob("*.py")):
                if int(path.name[:4]) <= 17:
                    migration(path).upgrade()
            connection.execute(
                text(
                    "INSERT INTO integration_states (key,revision,data) "
                    "VALUES ('feishu',7,CAST(:data AS JSON))"
                ),
                {
                    "data": '{"app_id":"provider-current","tenant_key":"tenant",'
                    '"verified":true,"enabled":true}'
                },
            )
            for name, id in ids.items():
                connection.execute(
                    text("""
                        INSERT INTO users
                          (id,kind,username,display_name,password_hash,tenant_key,open_id)
                        VALUES (:id,:kind,:username,:name,:password_hash,:tenant,:open_id)
                    """),
                    dict(
                        id=id,
                        kind="local" if name == "local" else "feishu",
                        username="admin" if name == "local" else None,
                        name=name,
                        password_hash="fixture-hash" if name == "local" else None,
                        tenant=None
                        if name == "local"
                        else "other"
                        if name == "foreign"
                        else "tenant",
                        open_id=None if name == "local" else name,
                    ),
                )
                if name != "local":
                    connection.execute(
                        text("""
                            INSERT INTO auth_sessions
                              (id,token_hash,csrf_hash,user_id,kind,created_at,expires_at,
                               authenticated_at,feishu_config_revision)
                            VALUES (:id,:hash,'fixture-hash',:user_id,'feishu',now(),
                              now()+interval '1 hour',now(),:revision)
                        """),
                        dict(
                            id=uuid4(), hash=name, user_id=id, revision=6 if name == "stale" else 7
                        ),
                    )
            before = connection.execute(
                text("SELECT id,password_hash FROM users ORDER BY id")
            ).all()
            module = migration(directory / "0018_access_roles.py")
            module.upgrade()
            rows = {
                row["display_name"]: row
                for row in connection.execute(text("SELECT * FROM users")).mappings()
            }
            assert rows["local"]["global_role"] == "admin"
            assert rows["proven"]["provider_app_id"] == "provider-current"
            assert rows["proven"]["identity_verified_at"] is not None
            for name in ("proven", "stale", "foreign"):
                assert rows[name]["global_role"] == "downloader"
                assert rows[name]["permission_revision"] == 1 and rows[name]["active"]
            for name in ("stale", "foreign"):
                assert rows[name]["provider_app_id"] is None
                assert rows[name]["identity_verified_at"] is None
            assert connection.execute(text("SELECT count(*) FROM app_roles")).scalar() == 0
            assert (
                connection.execute(text("SELECT id,password_hash FROM users ORDER BY id")).all()
                == before
            )
            module.downgrade()
            assert (
                connection.execute(text("SELECT id,password_hash FROM users ORDER BY id")).all()
                == before
            )
            module.upgrade()
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
