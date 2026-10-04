"""Provider-backed batch imports and database-persisted opt-in schedules."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_github_api import (
    create_bound_app,
    create_connector,
    initialize,
    make_release,
)
from test_github_api import (
    github_client as github_client_fixture,
)

from app.domains.auth.service import utcnow
from app.domains.distribution.models import DebugRecord, TaskRecord
from app.domains.github.models import GithubReleasePolicy
from app.domains.github.releases import schedule_release_checks
from app.domains.github.service import sync_releases
from app.workers.tasks import execute_task

RULES = {
    "asset_patterns": ["*.apk", "*.ipa"],
    "exclude_patterns": [],
    "tag_pattern": "*",
    "prerelease": "all",
}

github_client = github_client_fixture


def setup(client):
    headers = initialize(client)
    app = create_bound_app(client, headers, create_connector(client, headers))
    with Session(client.app.state.engine) as db:
        sync_releases(db, app["id"], client.app.state.settings)
    return headers, app, f"/api/v1/apps/{app['id']}/github/releases"


def preview(client, headers, url, rules=RULES):
    response = client.post(url + "/preview", json=rules, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, headers, url, rules=RULES, snapshot=None, key=None):
    data = snapshot or preview(client, headers, url, rules)
    return client.post(
        url + "/import",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={"rules": rules, "snapshot_token": data["snapshot_token"]},
    )


def execute(client, task_id):
    execute_task(client.app.state.engine, client.app.state.settings, task_id)
    return client.get(f"/api/v1/tasks/{task_id}").json()


def test_rules_match_all_pages_and_filter_drafts_platform_size(github_client):
    client, provider = github_client
    provider["releases"] = [make_release(i, f"joice-{i}-arm64.apk") for i in range(1, 104)]
    provider["releases"][0]["draft"] = True
    provider["releases"][1]["prerelease"] = True
    provider["releases"][2]["assets"][0]["size"] = 0
    headers, _, url = setup(client)
    rules = {
        **RULES,
        "asset_patterns": ["joice-*-arm64.apk"],
        "exclude_patterns": ["joice-4-*"],
        "prerelease": "exclude",
    }
    matched = preview(client, headers, url, rules)
    assert matched["matched_count"] == 99
    assert matched["skipped_count"] == 4
    assert matched["items"][-1]["release_id"] == "103"
    assert preview(client, headers, url, {**RULES, "tag_pattern": "v10?"})["matched_count"] == 4
    assert (
        client.post(
            url + "/preview", headers=headers, json={**RULES, "asset_patterns": [" "]}
        ).status_code
        == 422
    )


def test_batch_import_idempotency_and_stale_preview(github_client):
    client, provider = github_client
    headers, _, url = setup(client)
    initial = preview(client, headers, url)
    key = str(uuid4())
    response = submit(client, headers, url, snapshot=initial, key=key)
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    assert submit(client, headers, url, snapshot=initial, key=key).json()["task_id"] == task_id
    assert execute(client, task_id)["state"] == "succeeded"
    assert preview(client, headers, url)["existing_count"] == 2
    repeated = submit(client, headers, url)
    assert execute(client, repeated.json()["task_id"])["state"] == "succeeded"
    result = client.get(url + "/policy").json()["last_result"]
    assert result["created_count"] == 0 and result["existing_count"] == 2
    assert (
        client.post(
            url + "/import",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={
                "rules": {**RULES, "tag_pattern": "v1"},
                "snapshot_token": initial["snapshot_token"],
            },
        ).status_code
        == 409
    )


def test_changed_asset_is_not_silently_imported_and_other_releases_succeed(github_client):
    client, provider = github_client
    provider["releases"][0]["assets"].append(make_release(9, "universal.apk")["assets"][0])
    headers, _, url = setup(client)
    response = submit(client, headers, url)
    provider["releases"][0]["assets"][0]["size"] = 8
    task_id = response.json()["task_id"]
    result = execute(client, task_id)
    assert result["state"] == "partial_success", result
    assert result["can_retry"] is True
    summary = client.get(url + "/policy").json()["last_result"]
    assert summary["created_count"] == 2 and summary["failed_count"] == 1
    assert summary["errors"][0]["error_code"] == "RELEASE_ASSET_CHANGED"
    # Retrying an unchanged plan cannot consume the replacement asset.
    retry = client.post(
        f"/api/v1/tasks/{task_id}/retry", headers={**headers, "Idempotency-Key": str(uuid4())}
    )
    assert retry.status_code == 202
    assert execute(client, task_id)["state"] == "partial_success"
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(DebugRecord)) == 2


def test_polling_is_opt_in_and_discovers_new_and_replaced_assets(github_client):
    client, provider = github_client
    headers, app, url = setup(client)
    now = utcnow()
    with Session(client.app.state.engine) as db:
        schedule_release_checks(db, now)
        db.commit()
        assert db.scalar(select(func.count()).select_from(TaskRecord)) == 0
    body = {"rules": RULES, "auto_enabled": True, "interval_minutes": 5}
    response = client.put(url + "/policy", headers={**headers, "If-Match": '"0"'}, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["next_check_at"]
    assert (
        client.put(url + "/policy", headers={**headers, "If-Match": '"0"'}, json=body).status_code
        == 412
    )
    for iteration in range(3):
        if iteration == 1:
            provider["releases"].append(make_release(3))
            provider["releases"][0]["assets"][0]["updated_at"] = "2026-10-02T00:00:00Z"
        with Session(client.app.state.engine) as db:
            due = utcnow() + timedelta(minutes=iteration * 6)
            schedule_release_checks(db, due)
            schedule_release_checks(db, due)
            db.commit()
            policy = db.get(GithubReleasePolicy, UUID(app["id"]))
            task_id = policy.last_task_id
            assert (
                db.scalar(
                    select(func.count()).select_from(TaskRecord).where(TaskRecord.state == "queued")
                )
                == 1
            )
        assert execute(client, task_id)["state"] == "succeeded"
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(DebugRecord)) == 4
    result = client.get(url + "/policy").json()["last_result"]
    assert result["created_count"] == 0 and result["existing_count"] == 3


def test_disabling_rule_stops_queued_automatic_import(github_client):
    client, _ = github_client
    headers, app, url = setup(client)
    body = {"rules": RULES, "auto_enabled": True, "interval_minutes": 15}
    assert (
        client.put(url + "/policy", headers={**headers, "If-Match": '"0"'}, json=body).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        schedule_release_checks(db, utcnow() + timedelta(seconds=1))
        db.commit()
        task_id = db.get(GithubReleasePolicy, UUID(app["id"])).last_task_id
    disabled = client.put(
        url + "/policy",
        headers={**headers, "If-Match": '"1"'},
        json={**body, "auto_enabled": False},
    )
    assert disabled.status_code == 200
    result = execute(client, task_id)
    assert result["state"] == "failed" and result["error_code"] == "RELEASE_POLICY_CHANGED"
    assert client.get(url + "/policy").json()["next_check_at"] is None
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(DebugRecord)) == 0
