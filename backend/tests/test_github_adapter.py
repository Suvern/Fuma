import base64
import hashlib
import socket

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.domains.github.crypto import SecretBox
from app.domains.github.service import release_dto
from app.integrations.github import (
    GitHubClient,
    GitHubError,
    repository_path,
    validate_download_url,
)


def test_secret_box_random_nonce_scope_and_wrong_key():
    box = SecretBox(Settings(encryption_key=base64.urlsafe_b64encode(b"a" * 32).decode()))
    value = "synthetic-token-for-test"
    encrypted = box.encrypt(value, "github:one")
    assert encrypted != box.encrypt(value, "github:one")
    assert value not in encrypted
    assert box.decrypt(encrypted, "github:one") == value
    for scope in ["github:two", "feishu"]:
        with pytest.raises(AppError, match="凭据无法解密"):
            box.decrypt(encrypted, scope)
    other = SecretBox(Settings(encryption_key=base64.urlsafe_b64encode(b"b" * 32).decode()))
    with pytest.raises(AppError):
        other.decrypt(encrypted, "github:one")
    with pytest.raises(AppError):
        SecretBox(Settings(encryption_key="invalid"))


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/a",
        "https://evil.test/a",
        "https://127.0.0.1/a",
        "https://api.github.com.evil.test/a",
        "https://x@api.github.com/a",
        "https://api.github.com:444/a",
        "https://api.github.com/a#fragment",
    ],
)
def test_unsafe_download_targets_are_rejected(url):
    with pytest.raises(GitHubError) as error:
        validate_download_url(url, resolve_dns=False)
    assert error.value.code == "UNSAFE_REDIRECT"


def test_dns_private_result_and_mixed_result_fail_closed(monkeypatch):
    for addresses in [["127.0.0.1"], ["140.82.112.5", "10.0.0.1"], ["::1"]]:
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *_, addresses=addresses, **__: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
            ],
        )
        with pytest.raises(GitHubError) as error:
            validate_download_url("https://api.github.com/a")
        assert error.value.code == "UNSAFE_REDIRECT"


def test_resolution_is_pinned_with_host_and_tls_hostname(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_, **__: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.112.5", 443))],
    )
    captured = []

    class Transport(httpx.BaseTransport):
        def handle_request(self, request):
            captured.append(request)
            return httpx.Response(200, json={"id": 1})

    with GitHubClient("test-token", transport=Transport()) as client:
        assert client.get_repository("owner/repo")["id"] == 1
    request = captured[0]
    assert request.url.host == "140.82.112.5"
    assert request.headers["host"] == "api.github.com"
    assert request.extensions["sni_hostname"] == "api.github.com"


def test_repository_traversal_and_asset_identifiers_rejected():
    for name in ["../repo", "owner/..", "owner/repo/extra", "//evil"]:
        with pytest.raises(GitHubError):
            repository_path(name)
    with GitHubClient("test", transport=httpx.MockTransport(lambda _: None)) as client:
        with pytest.raises(GitHubError):
            client.get_asset("owner/repo", "1?evil=yes")


def test_paginate_release_and_asset_lists_to_completion():
    seen = []

    def handle(request):
        page = int(request.url.params["page"])
        seen.append((request.url.path, page))
        if request.url.path.endswith("/releases"):
            return httpx.Response(200, json=[{"id": 7}])
        return httpx.Response(
            200, json=[{"id": i} for i in range(100)] if page == 1 else [{"id": 101}]
        )

    with GitHubClient("test", transport=httpx.MockTransport(handle)) as client:
        rows = client.list_releases("owner/repo")
    assert len(rows[0]["assets"]) == 101
    assert ("/repos/owner/repo/releases/7/assets", 2) in seen


@pytest.mark.parametrize(
    "status,headers,code",
    [
        (401, {}, "GITHUB_BAD_CREDENTIAL"),
        (403, {}, "GITHUB_FORBIDDEN"),
        (404, {}, "GITHUB_NOT_FOUND"),
        (429, {"retry-after": "120"}, "GITHUB_RATE_LIMITED"),
        (403, {"x-ratelimit-remaining": "0"}, "GITHUB_RATE_LIMITED"),
        (503, {}, "GITHUB_UNAVAILABLE"),
    ],
)
def test_provider_failure_is_sanitized(status, headers, code):
    with GitHubClient(
        "test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status, headers=headers, json={"message": "private-provider-detail"}
            )
        ),
    ) as client:
        with pytest.raises(GitHubError) as error:
            client.get_repository("owner/repo")
    assert error.value.code == code
    assert "private-provider-detail" not in str(error.value)


def test_download_redirect_strips_auth_and_streams_hash(tmp_path):
    seen = []
    payload = b"PK-test-content"

    def handle(request):
        seen.append(request)
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={"location": "https://release-assets.githubusercontent.com/file?signed=x"},
            )
        return httpx.Response(200, content=payload)

    path = tmp_path / "package.part"
    progress = []
    with GitHubClient("synthetic-secret", transport=httpx.MockTransport(handle)) as client:
        result = client.download_asset(
            "owner/repo", 4, path, len(payload), progress=progress.append
        )
    assert seen[0].headers["authorization"] == "Bearer synthetic-secret"
    assert "authorization" not in seen[1].headers
    assert path.read_bytes() == payload
    assert result == {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    assert progress[-1] == len(payload)


def test_incomplete_stream_and_interrupted_fsync_remove_partial_file(tmp_path, monkeypatch):
    class Partial(httpx.SyncByteStream):
        def __iter__(self):
            yield b"half"
            raise httpx.ReadError("private-stream-detail")

    path = tmp_path / "package.part"
    with GitHubClient(
        "test", transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Partial()))
    ) as client:
        with pytest.raises(GitHubError):
            client.download_asset("owner/repo", 3, path, 8)
    assert not path.exists()
    monkeypatch.setattr(
        "app.integrations.github.os.fsync", lambda _: (_ for _ in ()).throw(OSError("disk full"))
    )
    with GitHubClient(
        "test", transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"abcd"))
    ) as client:
        with pytest.raises(OSError):
            client.download_asset("owner/repo", 3, path, 4)
    assert not path.exists()


def test_source_size_change_and_symlink_never_overwrite(tmp_path):
    destination, victim = tmp_path / "cache", tmp_path / "victim"
    victim.write_bytes(b"untouched")
    destination.symlink_to(victim)
    with GitHubClient(
        "test", transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"abcd"))
    ) as client:
        with pytest.raises(GitHubError):
            client.download_asset("owner/repo", 3, destination, 5)
        with pytest.raises(FileExistsError):
            client.download_asset("owner/repo", 3, destination, 4)
    assert victim.read_bytes() == b"untouched"


def test_run_attempt_endpoint_and_annotated_tag_commit():
    seen = []
    commit = "a" * 40

    def handle(request):
        seen.append(request.url.path)
        if "/attempts/" in request.url.path:
            return httpx.Response(200, json={"run_attempt": 2})
        if "/git/ref/" in request.url.path:
            return httpx.Response(200, json={"object": {"type": "tag", "sha": "b" * 40}})
        return httpx.Response(200, json={"object": {"type": "commit", "sha": commit}})

    with GitHubClient("test", transport=httpx.MockTransport(handle)) as client:
        assert client.get_run("owner/repo", 100, 2)["run_attempt"] == 2
        assert client.tag_commit("owner/repo", "v1.0") == commit
    assert "/repos/owner/repo/actions/runs/100/attempts/2" in seen


def test_release_public_dto_never_exposes_asset_urls():
    row = {
        "id": 1,
        "name": None,
        "tag_name": "v1",
        "draft": False,
        "prerelease": True,
        "body": "notes",
        "published_at": None,
        "assets": [
            {
                "id": 2,
                "name": "debug.apk",
                "size": 4,
                "updated_at": "2026-10-01T00:00:00Z",
                "browser_download_url": "secret-url",
            }
        ],
    }
    dto = release_dto(row)
    assert dto.assets[0].supported
    assert dto.assets[0].platform == "android"
    assert "secret-url" not in dto.model_dump_json()
    row["draft"] = True
    assert not release_dto(row).assets[0].supported
