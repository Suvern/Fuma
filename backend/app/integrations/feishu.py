"""Fixed-origin Feishu API client. Provider bodies and tokens never become errors/logs."""

import json

import httpx

from app.core.errors import AppError


class FeishuClient:
    def __init__(self, app_id, secret, transport=None):
        self.app_id, self.secret = app_id, secret
        self.http = httpx.Client(
            base_url="https://open.feishu.cn",
            transport=transport,
            timeout=20,
            follow_redirects=False,
            trust_env=False,
        )
        self._token = None

    def close(self):
        self.http.close()

    def request(self, method, path, *, token=None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = self.http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise AppError(503, "PROVIDER_UNAVAILABLE", "飞书暂时不可用", retryable=True) from None
        if response.status_code == 429:
            raise AppError(503, "PROVIDER_RATE_LIMITED", "飞书请求频率受限", retryable=True)
        if response.status_code >= 500:
            raise AppError(503, "PROVIDER_UNAVAILABLE", "飞书暂时不可用", retryable=True)
        try:
            body = response.json()
        except ValueError:
            raise AppError(502, "PROVIDER_INVALID_RESPONSE", "飞书返回内容无效") from None
        if not isinstance(body, dict):
            raise AppError(502, "PROVIDER_INVALID_RESPONSE", "飞书返回内容无效")
        if response.status_code >= 300 or body.get("code", 0) != 0:
            raise AppError(400, "FEISHU_REQUEST_REJECTED", "飞书拒绝请求，请检查应用权限及配置")
        return body

    def tenant_token(self):
        if self._token is None:
            data = self.request(
                "POST",
                "/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.secret},
            )
            self._token = data.get("tenant_access_token")
            if not self._token:
                raise AppError(502, "PROVIDER_INVALID_RESPONSE", "飞书未返回应用访问令牌")
        return self._token

    def oauth_user(self, code, redirect_uri):
        data = self.request(
            "POST",
            "/open-apis/authen/v2/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": self.app_id,
                "client_secret": self.secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        access = data.get("access_token") or data.get("data", {}).get("access_token")
        if not access:
            raise AppError(400, "OAUTH_EXCHANGE_FAILED", "飞书登录授权无效，请重新登录")
        user = self.request("GET", "/open-apis/authen/v1/user_info", token=access).get("data", {})
        if not user.get("tenant_key") or not user.get("open_id"):
            raise AppError(403, "ELIGIBILITY_UNVERIFIED", "无法核实飞书租户身份")
        return user

    def bot_info(self):
        data = self.request("GET", "/open-apis/bot/v3/info/", token=self.tenant_token())
        bot = data.get("bot", data.get("data", {}).get("bot", {}))
        if not bot.get("open_id"):
            raise AppError(400, "BOT_NOT_AVAILABLE", "请为同一自建应用启用机器人能力")
        return bot

    def chats(self):
        chats, seen, page_token = [], set(), None
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self.request(
                "GET", "/open-apis/im/v1/chats", token=self.tenant_token(), params=params
            ).get("data", {})
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("items"), list)
                or not isinstance(data.get("has_more"), bool)
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("chat_id"), str)
                    or not item["chat_id"]
                    or not isinstance(item.get("name"), str)
                    for item in data.get("items", [])
                )
            ):
                raise AppError(502, "PROVIDER_INVALID_RESPONSE", "飞书群列表内容不完整")
            chats.extend(data.get("items", []))
            if not data.get("has_more"):
                return chats
            page_token = data.get("page_token")
            if not page_token or page_token in seen or len(seen) >= 10000:
                raise AppError(502, "PROVIDER_INVALID_RESPONSE", "飞书群分页无效")
            seen.add(page_token)

    def send_card(self, chat_id, card, request_uuid):
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md" if card.get("body_format") == "lark_md" else "plain_text",
                    "content": card["summary"][:2000],
                },
            }
        ]
        actions = []
        if card.get("page_url"):
            actions.append(
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": card.get("button_text", "查看安装包")[:30],
                    },
                    "type": "primary",
                    "url": card["page_url"],
                }
            )
        if card.get("sub_button_text") and card.get("sub_button_url"):
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": card["sub_button_text"][:30]},
                    "type": "default",
                    "url": card["sub_button_url"],
                }
            )
        if actions:
            if card.get("header_color"):
                elements.append({"tag": "hr"})
            elements.append({"tag": "action", "actions": actions})
        content = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": card["title"][:100]}},
            "elements": elements,
        }
        if card.get("header_color"):
            content["header"]["template"] = card["header_color"]
        data = self.request(
            "POST",
            "/open-apis/im/v1/messages",
            token=self.tenant_token(),
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "uuid": str(request_uuid),
                "content": json.dumps(content, ensure_ascii=False),
            },
        )
        message_id = data.get("data", {}).get("message_id")
        if not message_id:
            raise AppError(502, "EXTERNAL_RESULT_UNKNOWN", "飞书投递结果不明确")
        return message_id
