import json

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.feishu import FeishuClient


def test_custom_card_fields_are_sent_as_plain_text_with_fixed_destination():
    sent = []

    def handler(request):
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"tenant_access_token": "synthetic-token"})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"message_id": "message-id"}})

    api = FeishuClient("app", "secret", transport=httpx.MockTransport(handler))
    try:
        api.send_card(
            "test-chat",
            {
                "title": "Joice 发布",
                "summary": "第一行\n<at id=all>",
                "button_text": "打开安装页",
                "header_color": "green",
                "page_url": "https://example.com/apps/1",
            },
            "request-1",
        )
    finally:
        api.close()
    card = json.loads(sent[0]["content"])
    assert card["header"]["template"] == "green"
    assert card["elements"][0]["text"] == {"tag": "plain_text", "content": "第一行\n<at id=all>"}
    assert card["elements"][1] == {"tag": "hr"}
    button = card["elements"][2]["actions"][0]
    assert button["text"]["content"] == "打开安装页"
    assert button["url"] == "https://example.com/apps/1"


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
