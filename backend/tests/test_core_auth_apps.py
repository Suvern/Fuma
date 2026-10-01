"""Real PostgreSQL auth transaction coverage, without Docker or dotenv."""

import base64
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import Depends, Response
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_downloader
from app.core.config import Settings
from app.core.errors import AppError
from app.domains.auth.models import AuthSession, User
from app.domains.auth.service import (
    create_user_session,
    initialize_admin,
    password_hasher,
    token_hash,
    utcnow,
    verify_password,
)
from app.domains.system.models import SystemState
from app.infrastructure.database import Base, build_engine
from app.main import create_app


@pytest.fixture
def core_app(tmp_path, initial_password_log):
    settings = Settings(
        database_url="postgresql+psycopg://fuma@127.0.0.1:55432/fuma_core_test",
        state_dir=tmp_path / "state",
        encryption_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    )
    engine = build_engine(settings)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception:
        engine.dispose()
        pytest.skip("isolated native PostgreSQL fuma_core_test unavailable")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(SystemState(id=1))
        db.commit()
    app = create_app(settings)
    app.state.initial_password_log = initial_password_log
    app.state.test_engine = engine
    yield app
    engine.dispose()


@pytest.fixture
def client(core_app):
    with TestClient(core_app, raise_server_exceptions=False) as client:
        yield client


def headers(client):
    result = client.get("/api/v1/auth/browser-context")
    assert result.status_code == 200, result.text
    return {"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": result.json()["csrf_token"]}


def login_initial(client):
    password = client.app.state.initial_password_log.call_args.args[1]
    result = client.post(
        "/api/v1/auth/login",
        headers=headers(client),
        json={"username": "admin", "password": password},
    )
    assert result.status_code == 200
    assert result.json()["user"]["must_change_password"] is True
    return {"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": result.json()["csrf_token"]}


def complete_first_login(client):
    hdr = login_initial(client)
    result = client.post(
        "/api/v1/auth/password",
        headers=hdr,
        json={
            "old_password": client.app.state.initial_password_log.call_args.args[1],
            "new_password": "Test-password-123",
        },
    )
    assert result.status_code == 200
    return {"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": result.json()["csrf_token"]}


def test_csrf_origin_anonymous_and_hash_storage(client):
    hdr = headers(client)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/apps").status_code == 401
    with Session(client.app.state.engine) as db:
        session = db.scalar(select(AuthSession))
        assert session.token_hash == token_hash(client.cookies.get("fuma_session"))
        assert session.csrf_hash != hdr["X-CSRF-Token"]
    payload = {"username": "admin", "password": "incorrect"}
    assert client.post("/api/v1/auth/login", json=payload).status_code == 403
    hdr["Origin"] = "https://attacker.test"
    assert client.post("/api/v1/auth/login", headers=hdr, json=payload).status_code == 403


def test_initial_password_restriction_rotation_and_logout(client):
    hdr = login_initial(client)
    old_cookie = client.cookies.get("fuma_session")
    assert client.get("/api/v1/auth/bootstrap-status").json()["initialized"]
    assert client.get("/api/v1/auth/me").json()["user"]["must_change_password"]
    assert client.get("/api/v1/auth/browser-context").json()["user"]["must_change_password"]
    for path in ("/api/v1/apps", "/api/v1/connectors/github", "/api/v1/settings/feishu"):
        result = client.get(path)
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.post("/api/v1/auth/bootstrap", headers=hdr, json={}).status_code == 404
    initial = client.app.state.initial_password_log.call_args.args[1]
    result = client.post(
        "/api/v1/auth/password",
        headers=hdr,
        json={"old_password": initial, "new_password": initial},
    )
    assert result.status_code == 422
    result = client.post(
        "/api/v1/auth/password",
        headers=hdr,
        json={"old_password": initial, "new_password": "New-password-456"},
    )
    assert result.status_code == 200
    assert result.json()["user"]["must_change_password"] is False
    assert client.cookies.get("fuma_session") != old_cookie
    assert client.get("/api/v1/apps").status_code == 200
    with Session(client.app.state.engine) as db:
        old = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(old_cookie)))
        assert old.revoked_at is not None
        assert db.scalar(select(User)).password_hash.startswith("$argon2id$")
    hdr["X-CSRF-Token"] = result.json()["csrf_token"]
    assert client.post("/api/v1/auth/logout", headers=hdr).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    result = client.post(
        "/api/v1/auth/login",
        headers=headers(client),
        json={"username": "admin", "password": initial},
    )
    assert result.status_code == 401
    result = client.post(
        "/api/v1/auth/login",
        headers=headers(client),
        json={"username": "admin", "password": "New-password-456"},
    )
    assert result.status_code == 200
    assert result.json()["user"]["must_change_password"] is False


def test_concurrent_startup_logs_once_and_restart_preserves_password(
    core_app, initial_password_log
):
    engine = core_app.state.test_engine
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(initialize_admin, [engine, engine]))
    assert initial_password_log.call_count == 1
    with Session(engine) as db:
        users = db.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].must_change_password is True
        stored = users[0].password_hash
        assert verify_password(stored, initial_password_log.call_args.args[1])
    initialize_admin(engine)
    assert initial_password_log.call_count == 1
    with Session(engine) as db:
        assert db.scalar(select(User)).password_hash == stored


def test_existing_admin_not_reset(core_app, initial_password_log):
    engine = core_app.state.test_engine
    stored = password_hasher.hash("Previously-set-password")
    with Session(engine) as db:
        db.get(SystemState, 1).initialized_at = utcnow()
        db.add(User(kind="local", username="admin", display_name="admin", password_hash=stored))
        db.commit()
    initialize_admin(engine)
    assert initial_password_log.call_count == 0
    with Session(engine) as db:
        user = db.scalar(select(User))
        assert user.password_hash == stored
        assert user.must_change_password is False


def test_initialized_state_missing_admin_fails_closed(core_app, initial_password_log):
    engine = core_app.state.test_engine
    with Session(engine) as db:
        db.get(SystemState, 1).initialized_at = utcnow()
        db.commit()
    with pytest.raises(AppError) as error:
        initialize_admin(engine)
    assert error.value.code == "ADMIN_STATE_INVALID"
    assert initial_password_log.call_count == 0
    with Session(engine) as db:
        assert db.scalar(select(User)) is None


def test_initialization_commit_failure_does_not_log(core_app, initial_password_log, monkeypatch):
    def fail_commit(_db):
        raise RuntimeError("synthetic commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            initialize_admin(core_app.state.test_engine)
    assert initial_password_log.call_count == 0
    with Session(core_app.state.test_engine) as db:
        assert db.scalar(select(User)) is None
        assert db.get(SystemState, 1).initialized_at is None


def test_durable_login_rate_limit(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/login",
                headers=headers(client),
                json={"username": "admin", "password": "incorrect"},
            ).status_code
            == 401
        )
    client.cookies.clear()
    assert (
        client.post(
            "/api/v1/auth/login",
            headers=headers(client),
            json={"username": "admin", "password": "incorrect"},
        ).status_code
        == 429
    )


def test_app_crud_idempotency_revision_audit(client):
    hdr = complete_first_login(client)
    hdr["Idempotency-Key"] = str(uuid4())
    body = {"name": "测试 App", "public_slug": "test-app", "platforms": ["android"]}
    result = client.post("/api/v1/apps", headers=hdr, json=body)
    assert result.status_code == 201, result.text
    assert result.headers["ETag"] == '"1"'
    app_id = result.json()["id"]
    replay = client.post("/api/v1/apps", headers=hdr, json=body)
    assert replay.status_code == 201 and replay.json()["id"] == app_id
    assert (
        client.post("/api/v1/apps", headers=hdr, json={**body, "name": "changed"}).status_code
        == 409
    )
    hdr["Idempotency-Key"] = str(uuid4())
    assert client.post("/api/v1/apps", headers=hdr, json=body).status_code == 409
    assert client.get("/api/v1/apps?q=测试&page_size=1").json()["total"] == 1
    hdr["If-Match"] = '"1"'
    result = client.patch(f"/api/v1/apps/{app_id}", headers=hdr, json={"enabled": False})
    assert result.status_code == 200 and result.headers["ETag"] == '"2"'
    assert (
        client.patch(f"/api/v1/apps/{app_id}", headers=hdr, json={"enabled": True}).status_code
        == 412
    )
    hdr["If-Match"] = '"2"'
    assert client.patch(f"/api/v1/apps/{app_id}", headers=hdr, json={}).status_code == 422
    assert client.delete(f"/api/v1/apps/{app_id}", headers=hdr).status_code == 204
    assert client.get(f"/api/v1/apps/{app_id}").status_code == 404
    assert client.get("/api/v1/audit-events?action=app.delete").json()["total"] == 1


def test_feishu_role_and_expired_qualification(client):
    client.app.add_api_route(
        "/test-download", lambda: {"ok": True}, dependencies=[Depends(require_downloader)]
    )
    with Session(client.app.state.engine) as db:
        user = User(kind="feishu", display_name="测试", tenant_key="tenant", open_id="user")
        db.add(user)
        db.flush()
        response = Response()
        session, _ = create_user_session(
            db,
            response,
            user,
            client.app.state.settings,
            eligibility_until=utcnow() + timedelta(seconds=300),
            config_revision=1,
        )
        session_id = session.id
        db.commit()
    cookie = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    client.cookies.set("fuma_session", cookie)
    assert client.get("/api/v1/apps").status_code == 403
    assert client.get("/test-download").status_code == 200
    with Session(client.app.state.engine) as db:
        session = db.get(AuthSession, session_id)
        session.eligibility_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/test-download").status_code == 403


def test_existing_account_migration_preserves_password(core_app):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    schema = "auth_migration_" + uuid4().hex
    directory = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    with core_app.state.test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with Operations.context(MigrationContext.configure(connection)):
            for path in sorted(directory.glob("000[1-5]*.py")):
                spec = importlib.util.spec_from_file_location(path.stem, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
            encoded = password_hasher.hash("Existing-password-123")
            connection.execute(
                text(
                    "INSERT INTO users (id,kind,username,display_name,password_hash) "
                    "VALUES (:id,'local','admin','admin',:hash)"
                ),
                {"id": uuid4(), "hash": encoded},
            )
            path = directory / "0006_initial_password.py"
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade()
            user = connection.execute(
                text("SELECT password_hash, must_change_password FROM users")
            ).one()
            assert user.password_hash == encoded
            assert user.must_change_password is False
            assert (
                connection.execute(
                    text("SELECT encryption_key_digest FROM system_state")
                ).scalar_one()
                is None
            )
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_operator_password_reset_clears_required_flag_and_revokes_sessions(client, monkeypatch):
    from app.cli import reset_admin

    login_initial(client)
    engine = client.app.state.engine
    monkeypatch.setattr(reset_admin.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(reset_admin.getpass, "getpass", lambda _prompt: "Operator-password-123")
    monkeypatch.setattr(reset_admin, "Settings", lambda: client.app.state.settings)
    monkeypatch.setattr(reset_admin, "build_engine", lambda _settings: engine)
    reset_admin.main()
    assert client.get("/api/v1/auth/me").status_code == 401
    with Session(engine) as db:
        user = db.scalar(select(User))
        assert user.must_change_password is False
        assert verify_password(user.password_hash, "Operator-password-123")
        assert all(row.revoked_at is not None for row in db.scalars(select(AuthSession)))
