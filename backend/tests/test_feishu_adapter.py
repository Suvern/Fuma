import json

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.feishu import FeishuClient


@pytest.mark.parametrize("with_secondary", [False, True])
@pytest.mark.parametrize("body_format", [None, "lark_md"])
def test_card_format_is_frozen_with_fixed_destination(with_secondary, body_format):
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
                "summary": "**第一行**\n第二行",
                **({"body_format": body_format} if body_format else {}),
                "button_text": "打开安装页",
                "header_color": "green",
                "page_url": "https://example.com/apps/1",
                **(
                    {
                        "sub_button_text": "应用下载页",
                        "sub_button_url": "https://example.com/apps/1",
                    }
                    if with_secondary
                    else {}
                ),
            },
            "request-1",
        )
    finally:
        api.close()
    card = json.loads(sent[0]["content"])
    assert card["header"]["template"] == "green"
    assert card["elements"][0]["text"] == {
        "tag": body_format or "plain_text",
        "content": "**第一行**\n第二行",
    }
    assert card["elements"][1] == {"tag": "hr"}
    button = card["elements"][2]["actions"][0]
    assert button["text"]["content"] == "打开安装页"
    assert button["url"] == "https://example.com/apps/1"
    if with_secondary:
        secondary = card["elements"][2]["actions"][1]
        assert secondary["type"] == "default"
        assert secondary["text"] == {"tag": "plain_text", "content": "应用下载页"}
        assert secondary["url"] == "https://example.com/apps/1"
    else:
        assert len(card["elements"][2]["actions"]) == 1


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
