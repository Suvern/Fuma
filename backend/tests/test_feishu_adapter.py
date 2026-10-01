import httpx
import pytest

from app.core.errors import AppError
from app.integrations.feishu import FeishuClient


def provider(body):
    def handler(request):
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "synthetic-test-token"}
            )
        return httpx.Response(200, json=body)

    return FeishuClient("synthetic-app", "synthetic-secret", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"items": [], "has_more": "false"},
        {"items": [{"name": "missing id"}], "has_more": False},
    ],
)
def test_incomplete_chat_snapshot_is_rejected(data):
    api = provider({"code": 0, "data": data})
    try:
        with pytest.raises(AppError, match="飞书群列表内容不完整") as error:
            api.chats()
        assert error.value.code == "PROVIDER_INVALID_RESPONSE"
    finally:
        api.close()


def test_all_pages_are_read_and_repeated_page_token_is_rejected():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "synthetic-test-token"}
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [{"chat_id": "oc_test", "name": "Test"}],
                    "has_more": True,
                    "page_token": "same-token",
                },
            },
        )

    api = FeishuClient("synthetic-app", "synthetic-secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError) as error:
            api.chats()
        assert error.value.code == "PROVIDER_INVALID_RESPONSE"
        assert len(requests) == 3
    finally:
        api.close()
