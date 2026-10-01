"""Read-only GitHub REST adapter. Provider payloads never become client error messages."""

import hashlib
import ipaddress
import json
import os
import re
import socket
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx

from app.core.errors import AppError

API_ORIGIN = "https://api.github.com"
API_VERSION = "2022-11-28"
DOWNLOAD_HOSTS = {
    "api.github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


class GitHubError(AppError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 503,
        retryable: bool = False,
        retry_after: int | None = None,
    ):
        super().__init__(status_code, code, message, retryable=retryable)
        self.retry_after = retry_after


def repository_path(full_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise GitHubError("INVALID_REPOSITORY", "仓库格式应为 owner/repo", 422)
    if any(segment in {".", ".."} for segment in full_name.split("/")):
        raise GitHubError("INVALID_REPOSITORY", "仓库格式不合法", 422)
    return "/repos/" + full_name


def provider_id(value: str | int) -> str:
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise GitHubError("INVALID_PROVIDER_ID", "来源资源标识不合法", 422)
    return str(value)


def validate_download_url(url: str, *, resolve_dns: bool = True) -> str | None:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in DOWNLOAD_HOSTS
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.fragment
            or any(ord(char) < 32 for char in url)
        ):
            raise ValueError
    except ValueError:
        raise GitHubError("UNSAFE_REDIRECT", "GitHub 下载重定向目标不被允许", 409) from None
    if resolve_dns:
        try:
            records = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
            if not records or any(not ipaddress.ip_address(row[4][0]).is_global for row in records):
                raise GitHubError("UNSAFE_REDIRECT", "GitHub 下载目标解析到非公网地址", 409)
            return records[0][4][0]
        except socket.gaierror:
            raise GitHubError(
                "GITHUB_NETWORK_ERROR", "无法解析 GitHub 服务地址", retryable=True
            ) from None
    return None


class GitHubClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self._token = token
        # Explicit MockTransport injects trusted test responses, never a runtime configuration.
        self._mock = isinstance(transport, httpx.MockTransport)
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _headers(self, binary: bool = False, authenticated: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "Fuma-M1",
            "Accept-Encoding": "identity",
        }
        if authenticated:
            headers["Authorization"] = "Bearer " + self._token
        return headers

    def _stream(self, url: str, *, binary: bool = False, params: dict | None = None):
        address = validate_download_url(url, resolve_dns=not self._mock)
        original = httpx.URL(url)
        headers = self._headers(binary, original.host == "api.github.com")
        extensions = {}
        if address:
            # Pin the validated resolution. httpcore uses sni_hostname for both TLS SNI
            # and certificate verification, preventing a second DNS lookup/rebinding gap.
            target = original.copy_with(host=address)
            headers["Host"] = original.host
            extensions["sni_hostname"] = original.host
        else:
            target = original
        return self._client.stream(
            "GET", target, headers=headers, params=params, extensions=extensions
        )

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        if response.status_code == 401:
            raise GitHubError("GITHUB_BAD_CREDENTIAL", "GitHub 凭据无效或已过期", 403)
        if response.status_code == 429 or (
            response.status_code == 403
            and (
                response.headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in response.headers
            )
        ):
            raw = response.headers.get("retry-after", "60")
            retry = min(max(int(raw), 1), 3600) if raw.isdecimal() else 60
            raise GitHubError(
                "GITHUB_RATE_LIMITED", "GitHub 请求受到限流，请稍后重试", 429, True, retry
            )
        if response.status_code == 403:
            raise GitHubError("GITHUB_FORBIDDEN", "GitHub 授权不足，请检查仓库权限", 403)
        if response.status_code == 404:
            raise GitHubError("GITHUB_NOT_FOUND", "GitHub 资源不存在或当前凭据无权读取", 404)
        if response.status_code in {301, 302, 303, 307, 308}:
            raise GitHubError("GITHUB_SOURCE_MOVED", "仓库来源已变化，请重新关联确认", 409)
        raise GitHubError(
            "GITHUB_UNAVAILABLE",
            "GitHub 服务暂时无法完成请求",
            retryable=response.status_code >= 500,
        )

    def _json(self, path: str, *, params: dict | None = None):
        if not path.startswith("/") or path.startswith("//"):
            raise GitHubError("INVALID_PROVIDER_PATH", "来源地址不合法", 422)
        try:
            with self._stream(API_ORIGIN + path, params=params) as response:
                self._check(response)
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_JSON_BYTES:
                        raise GitHubError(
                            "GITHUB_RESPONSE_TOO_LARGE", "GitHub 返回数据超过处理上限"
                        )
                result = json.loads(data)
                if not isinstance(result, (dict, list)):
                    raise ValueError
                return result
        except httpx.HTTPError:
            raise GitHubError(
                "GITHUB_NETWORK_ERROR", "GitHub 网络请求失败", retryable=True
            ) from None
        except (ValueError, UnicodeError):
            raise GitHubError("GITHUB_INVALID_RESPONSE", "GitHub 返回了无法识别的数据") from None

    def _object(self, path: str) -> dict:
        result = self._json(path)
        if not isinstance(result, dict):
            raise GitHubError("GITHUB_INVALID_RESPONSE", "GitHub 返回数据类型不匹配")
        return result

    def _all_pages(self, path: str, key: str | None = None) -> list[dict]:
        result = []
        total_size = 0
        # Fail closed rather than silently advertise a partial snapshot.
        for page in range(1, 501):
            payload = self._json(path, params={"per_page": 100, "page": page})
            items = payload.get(key) if key and isinstance(payload, dict) else payload
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise GitHubError("GITHUB_INVALID_RESPONSE", "GitHub 分页数据格式不合法")
            total_size += len(json.dumps(items).encode())
            if total_size > MAX_SNAPSHOT_BYTES:
                raise GitHubError("GITHUB_SNAPSHOT_TOO_LARGE", "来源快照超过内存处理上限")
            result.extend(items)
            if len(items) < 100:
                return result
        raise GitHubError("GITHUB_SNAPSHOT_TOO_LARGE", "仓库数据超过同步上限，未覆盖上次完整快照")

    def get_identity(self) -> dict:
        return self._object("/user")

    def get_repository(self, full_name: str) -> dict:
        return self._object(repository_path(full_name))

    def list_repositories(self) -> list[dict]:
        return self._all_pages("/user/repos")

    def list_releases(self, full_name: str) -> list[dict]:
        rows = self._all_pages(repository_path(full_name) + "/releases")
        total_size = 0
        for row in rows:
            # Embedded arrays need not contain every asset; always paginate the asset endpoint.
            row["assets"] = self.list_assets(full_name, row["id"])
            total_size += len(json.dumps(row).encode())
            if total_size > MAX_SNAPSHOT_BYTES:
                raise GitHubError("GITHUB_SNAPSHOT_TOO_LARGE", "Release 快照超过内存处理上限")
        return rows

    def list_assets(self, full_name: str, release_id: str | int) -> list[dict]:
        return self._all_pages(
            repository_path(full_name) + "/releases/" + provider_id(release_id) + "/assets"
        )

    def get_release(self, full_name: str, release_id: str | int) -> dict:
        row = self._object(repository_path(full_name) + "/releases/" + provider_id(release_id))
        row["assets"] = self.list_assets(full_name, release_id)
        return row

    def get_asset(self, full_name: str, asset_id: str | int) -> dict:
        return self._object(
            repository_path(full_name) + "/releases/assets/" + provider_id(asset_id)
        )

    def get_run(self, full_name: str, run_id: str | int, attempt: int) -> dict:
        if attempt < 1:
            raise GitHubError("INVALID_RUN_ATTEMPT", "构建次数不合法", 422)
        return self._object(
            repository_path(full_name)
            + "/actions/runs/"
            + provider_id(run_id)
            + "/attempts/"
            + str(attempt)
        )

    def get_workflow(self, full_name: str, workflow_id: str | int) -> dict:
        return self._object(
            repository_path(full_name) + "/actions/workflows/" + provider_id(workflow_id)
        )

    def check_actions(self, full_name: str) -> None:
        result = self._json(repository_path(full_name) + "/actions/runs", params={"per_page": 1})
        if not isinstance(result, dict) or not isinstance(result.get("workflow_runs"), list):
            raise GitHubError("GITHUB_INVALID_RESPONSE", "GitHub 构建查询数据格式不合法")

    def tag_commit(self, full_name: str, tag: str) -> str:
        row = self._object(repository_path(full_name) + "/git/ref/tags/" + quote(tag, safe=""))
        target = row.get("object", {})
        for _ in range(8):
            sha = target.get("sha", "")
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                break
            if target.get("type") == "commit":
                return sha
            if target.get("type") != "tag":
                break
            target = self._object(repository_path(full_name) + "/git/tags/" + sha).get("object", {})
        raise GitHubError("GITHUB_TAG_UNVERIFIED", "无法验证 Release Tag 对应提交", 409)

    def download_asset(
        self,
        full_name: str,
        asset_id: str | int,
        destination: str | Path,
        expected_size: int,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> dict:
        if expected_size < 1 or expected_size > 4 * 1024**3:
            raise GitHubError("ASSET_SIZE_INVALID", "安装包大小不在允许范围内", 409)
        url = API_ORIGIN + repository_path(full_name) + "/releases/assets/" + provider_id(asset_id)
        path = Path(destination)
        written = 0
        checksum = hashlib.sha256()
        opened = False
        complete = False
        try:
            for _ in range(6):
                with self._stream(url, binary=True) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise GitHubError("UNSAFE_REDIRECT", "下载重定向缺少目标", 409)
                        url = urljoin(url, location)
                        continue
                    self._check(response)
                    declared = response.headers.get("content-length")
                    if declared is not None and (
                        not declared.isdecimal() or int(declared) != expected_size
                    ):
                        raise GitHubError(
                            "SOURCE_CHANGED", "来源文件大小发生变化，请重新选择附件", 409
                        )
                    # Exclusive no-follow file creation. Caller chooses its own private cache path.
                    descriptor = os.open(
                        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                    )
                    opened = True
                    with os.fdopen(descriptor, "wb") as file:
                        for chunk in response.iter_bytes(chunk_size=256 * 1024):
                            written += len(chunk)
                            if written > expected_size:
                                raise GitHubError("SOURCE_CHANGED", "来源文件超出预期大小", 409)
                            file.write(chunk)
                            checksum.update(chunk)
                            if progress:
                                progress(written)
                        file.flush()
                        os.fsync(file.fileno())
                    if written != expected_size:
                        raise GitHubError("SOURCE_CHANGED", "来源文件长度与快照不一致", 409)
                    complete = True
                    return {"size_bytes": written, "sha256": checksum.hexdigest()}
            raise GitHubError("UNSAFE_REDIRECT", "下载重定向次数过多", 409)
        except httpx.HTTPError:
            raise GitHubError(
                "GITHUB_NETWORK_ERROR", "GitHub 文件传输中断", retryable=True
            ) from None
        finally:
            if opened and not complete:
                path.unlink(missing_ok=True)
