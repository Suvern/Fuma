"""Capability failures must identify the failed operation without guessing the cause."""

import httpx
import pytest

from app.domains.github.service import test_connection as check_connection
from app.integrations.github import GitHubClient


def run_check(failing_path=None, status=403, headers=None, releases=None, repository="owner/repo"):
    calls = []

    def handle(request):
        path = request.url.path
        calls.append(path)
        if path == failing_path:
            return httpx.Response(
                status, headers=headers or {}, json={"message": "private-provider-data"}
            )
        if path == "/user":
            return httpx.Response(200, json={"login": "test-owner"})
        if path.endswith("/releases"):
            return httpx.Response(200, json=[{"id": 7}] if releases is None else releases)
        if path.endswith("/assets"):
            return httpx.Response(200, json=[])
        if path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": []})
        return httpx.Response(200, json={"id": 1, "full_name": "owner/repo"})

    with GitHubClient("synthetic-test-token", transport=httpx.MockTransport(handle)) as client:
        checks, login = check_connection(client, repository, True)
    return {check.code: check for check in checks}, login, calls


def test_release_forbidden_identifies_contents_permission_and_preserves_actions_success():
    checks, login, _ = run_check("/repos/owner/repo/releases")
    assert login == "test-owner"
    assert checks["repository"].status == "pass"
    assert checks["contents"].status == "fail"
    assert checks["contents"].required_permission == "Contents · Read-only"
    assert checks["contents"].endpoint == "GET /repos/owner/repo/releases"
    assert "未返回唯一拒绝原因" in checks["contents"].remediation
    assert checks["assets"].status == "unknown"
    assert checks["actions"].status == "pass"
    assert "private-provider-data" not in str(checks)


def test_asset_failure_does_not_duplicate_or_fail_release_check():
    checks, _, _ = run_check("/repos/owner/repo/releases/7/assets")
    assert checks["contents"].status == "pass"
    assert checks["assets"].status == "fail"
    assert checks["assets"].required_permission == "Contents · Read-only"
    assert checks["actions"].status == "pass"


@pytest.mark.parametrize(
    ("status", "headers", "code", "hint"),
    [
        (401, {}, "GITHUB_BAD_CREDENTIAL", "替换令牌"),
        (404, {}, "GITHUB_NOT_FOUND", "无法仅凭此响应"),
        (403, {"x-github-sso": "required; url=https://private.test"}, "GITHUB_SSO_REQUIRED", "SSO"),
        (
            403,
            {"x-ratelimit-remaining": "0", "retry-after": "120"},
            "GITHUB_RATE_LIMITED",
            "120 秒",
        ),
        (503, {}, "GITHUB_UNAVAILABLE", "网络连接"),
    ],
)
def test_errors_provide_cause_specific_recovery(status, headers, code, hint):
    checks, _, _ = run_check("/repos/owner/repo/releases", status, headers)
    failure = checks["contents"]
    assert failure.error_code == code
    assert hint in failure.remediation
    assert "private.test" not in failure.model_dump_json()


def test_bad_identity_skips_downstream_requests():
    checks, login, calls = run_check("/user", 401)
    assert login is None
    assert calls == ["/user"]
    assert checks["identity"].status == "fail"
    assert all(check.status == "unknown" for code, check in checks.items() if code != "identity")


def test_invisible_repository_does_not_claim_contents_permission_is_missing():
    checks, _, calls = run_check("/repos/owner/repo", 404)
    assert checks["repository"].status == "fail"
    assert checks["contents"].status == "unknown"
    assert len(calls) == 2


def test_empty_release_and_identity_only_are_not_full_success():
    checks, _, _ = run_check(releases=[])
    assert checks["contents"].status == "pass"
    assert checks["assets"].status == "unknown"
    checks, _, calls = run_check(repository=None)
    assert calls == ["/user"]
    assert checks["contents"].status == "unknown"


def test_malformed_release_response_skips_assets_and_network_errors_do_not_imply_permissions():
    checks, _, calls = run_check(releases={"invalid": "payload"})
    assert checks["contents"].error_code == "GITHUB_INVALID_RESPONSE"
    assert checks["assets"].status == "unknown"
    assert not any(path.endswith("/assets") for path in calls)
    checks, _, _ = run_check("/repos/owner/repo/releases", 503)
    assert checks["contents"].required_permission is None
