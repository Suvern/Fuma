from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import DependencyChecks
from app.core.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def no_startup_dependencies(monkeypatch):
    # These tests exercise HTTP handling independently of database/filesystem bootstrap.
    monkeypatch.setattr("app.main.ensure_encryption_key", lambda *_: None)
    monkeypatch.setattr("app.main.initialize_admin", lambda *_: None)


@pytest.fixture
def client():
    with TestClient(create_app(Settings()), raise_server_exceptions=False) as client:
        yield client


def test_liveness_requires_no_external_connections(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fuma-api"}
    assert UUID(response.headers["X-Request-ID"])
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "database,redis,status",
    [("ok", "ok", 200), ("unavailable", "ok", 503), ("ok", "unavailable", 503)],
)
def test_readiness_reflects_dependency_failure(client, monkeypatch, database, redis, status):
    monkeypatch.setattr(
        "app.api.health.check_dependencies",
        lambda *_: DependencyChecks(database=database, redis=redis),
    )
    response = client.get("/api/v1/health/ready")
    assert response.status_code == status
    assert response.json()["checks"] == {"database": database, "redis": redis}


def test_framework_errors_follow_error_contract(client):
    response = client.get("/api/v1/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    response = client.post("/api/v1/health/live")
    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]


def test_internal_and_validation_errors_do_not_expose_input(caplog):
    app = create_app(Settings())

    @app.get("/crash")
    def crash():
        raise RuntimeError("private-provider-payload")

    @app.get("/validate")
    def validate(count: int):
        return count

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/crash")
        assert response.status_code == 500
        assert "private-provider-payload" not in response.text
        assert "private-provider-payload" not in caplog.text
        assert "exception_type=RuntimeError" in caplog.text
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        response = client.get("/validate?count=private-input")
        assert response.status_code == 422
        assert "private-input" not in response.text
        assert response.json()["error"]["field_errors"][0]["field"] == "query.count"
