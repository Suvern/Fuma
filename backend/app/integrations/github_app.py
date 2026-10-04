"""Installation authentication for deployer-owned GitHub Apps; no OAuth marketplace."""

import base64
import json
import time
from datetime import datetime
from threading import Lock

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.integrations.github import API_ORIGIN, API_VERSION, GitHubClient, GitHubError, provider_id

_CACHE = {}
_LOCK = Lock()


def app_jwt(app_id, private_key):
    def encoded(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    try:
        key = serialization.load_pem_private_key(private_key.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError
        now = int(time.time())
        body = (
            encoded(b'{"alg":"RS256","typ":"JWT"}')
            + "."
            + encoded(
                json.dumps(
                    {"iat": now - 60, "exp": now + 540, "iss": provider_id(app_id)},
                    separators=(",", ":"),
                ).encode()
            )
        )
        return body + "." + encoded(key.sign(body.encode(), padding.PKCS1v15(), hashes.SHA256()))
    except Exception:
        raise GitHubError(
            "GITHUB_APP_KEY_INVALID", "GitHub App 私钥必须是有效的 RSA PEM（至少 2048 位）", 422
        ) from None


class GitHubAppClient(GitHubClient):
    def __init__(self, credentials, cache_key=None, transport=None):
        super().__init__("", transport=transport)
        self.credentials = credentials
        self.cache_key = cache_key
        self.expires = 0

    def _app_request(self, method, path):
        try:
            with self._client.stream(
                method,
                API_ORIGIN + path,
                headers={
                    "Authorization": "Bearer "
                    + app_jwt(self.credentials["app_id"], self.credentials["private_key"]),
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": API_VERSION,
                    "User-Agent": "Fuma",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code not in {200, 201}:
                    self._check(response)
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 1024 * 1024:
                        raise ValueError
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError
                return result
        except httpx.HTTPError:
            raise GitHubError(
                "GITHUB_NETWORK_ERROR", "无法连接 GitHub App 授权服务", retryable=True
            ) from None
        except (ValueError, KeyError, TypeError):
            raise GitHubError("GITHUB_INVALID_RESPONSE", "GitHub App 授权结果不完整") from None

    def _ensure_token(self):
        with _LOCK:
            cached = _CACHE.get(self.cache_key) if self.cache_key else None
            if cached and cached[1] > time.time() + 60:
                self._token, self.expires = cached
            if self.expires > time.time() + 60:
                return
            result = self._app_request(
                "POST",
                f"/app/installations/{provider_id(self.credentials['installation_id'])}/access_tokens",
            )
            try:
                token = result["token"]
                expires = datetime.fromisoformat(
                    result["expires_at"].replace("Z", "+00:00")
                ).timestamp()
                if (
                    not isinstance(token, str)
                    or not token
                    or not time.time() + 60 < expires <= time.time() + 3700
                ):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise GitHubError(
                    "GITHUB_INVALID_RESPONSE", "GitHub 安装令牌或有效期不合法"
                ) from None
            self._token, self.expires = token, expires
            if self.cache_key:
                # A changed connector revision uses a different bounded cache key.
                for key in list(_CACHE):
                    if _CACHE[key][1] <= time.time() + 60:
                        del _CACHE[key]
                if len(_CACHE) >= 256:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[self.cache_key] = (token, expires)

    def _stream(self, url, *, binary=False, params=None):
        self._ensure_token()
        return super()._stream(url, binary=binary, params=params)

    def _json(self, path, *, params=None):
        try:
            return super()._json(path, params=params)
        except GitHubError as exc:
            if exc.code != "GITHUB_BAD_CREDENTIAL":
                raise
            with _LOCK:
                _CACHE.pop(self.cache_key, None)
                self.expires = 0
            return super()._json(path, params=params)

    def get_identity(self):
        result = self._app_request(
            "GET", f"/app/installations/{provider_id(self.credentials['installation_id'])}"
        )
        if str(result.get("app_id")) != self.credentials["app_id"] or not result.get(
            "account", {}
        ).get("login"):
            raise GitHubError(
                "GITHUB_APP_INSTALLATION_MISMATCH", "安装实例与 GitHub App 不一致", 409
            )
        self._ensure_token()
        return {"login": result["account"]["login"]}

    def list_repositories(self):
        return self._all_pages("/installation/repositories", key="repositories")
