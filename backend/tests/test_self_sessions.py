from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_core_auth_apps import client as client
from test_core_auth_apps import complete_first_login
from test_core_auth_apps import core_app as core_app

from app.domains.audit.models import AuditRecord
from app.domains.auth.models import AuthSession, User
from app.domains.auth.service import utcnow


def test_self_sessions_hide_credentials_and_revoke_only_other_active_sessions(client):
    headers = complete_first_login(client)
    with Session(client.app.state.engine) as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        other = User(kind="feishu", display_name="其他用户", tenant_key="tenant", open_id="other")
        db.add(other)
        db.flush()

        def session(owner, expired=False):
            return AuthSession(
                user_id=owner,
                kind="local" if owner == user.id else "feishu",
                token_hash=uuid4().hex * 2,
                csrf_hash=uuid4().hex * 2,
                created_at=utcnow(),
                expires_at=utcnow() + timedelta(hours=-1 if expired else 1),
            )

        mine, expired, theirs = session(user.id), session(user.id, True), session(other.id)
        db.add_all([mine, expired, theirs])
        db.commit()
        mine_id, expired_id, theirs_id = mine.id, expired.id, theirs.id
    response = client.get("/api/v1/auth/sessions")
    assert response.status_code == 200
    rows = response.json()["items"]
    assert rows[0]["current"]
    assert all(row["id"] != str(theirs_id) for row in rows)
    assert all(not {"token_hash", "csrf_hash", "user_id", "ip"} & row.keys() for row in rows)
    assert client.post("/api/v1/auth/sessions/revoke-others").status_code == 403
    result = client.post("/api/v1/auth/sessions/revoke-others", headers=headers)
    assert result.json() == {"revoked_count": 1}
    assert client.get("/api/v1/auth/me").status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.get(AuthSession, mine_id).revoked_at
        assert db.get(AuthSession, expired_id).revoked_at is None
        assert db.get(AuthSession, theirs_id).revoked_at is None
        assert db.scalar(
            select(AuditRecord).where(AuditRecord.action == "account.revoke_other_sessions")
        )
    assert client.post("/api/v1/auth/sessions/revoke-others", headers=headers).json() == {
        "revoked_count": 0
    }
    client.cookies.clear()
    assert client.get("/api/v1/auth/sessions").status_code == 401
