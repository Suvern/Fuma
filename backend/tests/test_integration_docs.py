from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_agent_document_is_public_and_uses_configured_origin():
    # No lifespan or database: this public route must not read private rule settings.
    app = create_app(Settings(site_url="https://fuma.example", cookie_secure=True))
    client = TestClient(app, base_url="http://untrusted-host.example")
    rule_id = uuid4()
    response = client.get(f"/api/v1/docs/github-actions?rule_id={rule_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert (
        f"https://fuma.example/api/v1/integrations/github-actions/{rule_id}/cos-events" in response.text
    )
    assert "untrusted-host" not in response.text
    assert "文档不验证该规则是否存在" in response.text
    assert "contents: write" in response.text and "FUMA_CI_TOKEN" in response.text
    assert "{{CALLBACK_URL}}" not in response.text
    assert "<RULE_ID>" in client.get("/api/v1/docs/github-actions").text
    assert client.get("/api/v1/docs/github-actions?rule_id=invalid").status_code == 422


def test_public_workflow_example_matches_maintained_examples():
    root = Path(__file__).resolve().parents[2]
    packaged = (root / "backend/app/resources/github-actions-example.yml").read_text()
    assert packaged == (root / "deploy/github-actions-example.yml").read_text()
    assert packaged == (root / "frontend/src/features/m1/github-actions-example.yml").read_text()
