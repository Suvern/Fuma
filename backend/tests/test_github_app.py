import base64
import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.integrations.github import GitHubError
from app.integrations.github_app import GitHubAppClient, app_jwt


def credentials():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, {
        "app_id": "123",
        "installation_id": "456",
        "private_key": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    }


def test_jwt_signature_time_bounds_and_no_unsigned_algorithm():
    key, config = credentials()
    value = app_jwt(config["app_id"], config["private_key"])
    header, body, signature = value.split(".")

    def decode(item):
        return base64.urlsafe_b64decode(item + "=" * (-len(item) % 4))

    assert json.loads(decode(header))["alg"] == "RS256"
    claims = json.loads(decode(body))
    assert claims["iat"] <= time.time() - 59 and claims["exp"] <= time.time() + 541
    key.public_key().verify(
        decode(signature), (header + "." + body).encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    with pytest.raises(GitHubError):
        app_jwt("123", "not-a-key")


def test_installation_repository_scope_and_single_refresh_on_revocation():
    _, config = credentials()
    issued = 0

    def handler(request):
        nonlocal issued
        if request.url.path == "/app/installations/456":
            return httpx.Response(200, json={"app_id": 123, "account": {"login": "test-org"}})
        if request.method == "POST":
            issued += 1
            return httpx.Response(
                201,
                json={
                    "token": "synthetic-token-" + str(issued),
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
        assert request.url.path == "/installation/repositories"
        if issued == 1:
            return httpx.Response(401, json={})
        return httpx.Response(
            200, json={"repositories": [{"id": 9, "full_name": "test-org/mobile"}]}
        )

    with GitHubAppClient(config, transport=httpx.MockTransport(handler)) as client:
        assert client.get_identity() == {"login": "test-org"}
        assert client.list_repositories()[0]["id"] == 9
        assert issued == 2
        client.list_repositories()
        assert issued == 2


def test_wrong_installation_identity_is_rejected():
    _, config = credentials()
    with GitHubAppClient(
        config,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"app_id": 999, "account": {"login": "wrong"}})
        ),
    ) as client:
        with pytest.raises(GitHubError) as raised:
            client.get_identity()
        assert raised.value.code == "GITHUB_APP_INSTALLATION_MISMATCH"
