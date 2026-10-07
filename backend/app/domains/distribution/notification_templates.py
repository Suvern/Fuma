"""Plain-text Release card templates, rendered once before delivery is queued."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.errors import AppError
from app.domains.distribution.models import IntegrationState

STATE_KEY = "release_notification_template"
DEFAULT_TEMPLATE = {
    "title": "{{app_name}} · 新安装包已就绪",
    "body": (
        "版本：{{version}}\nBuild：{{buildNumber}}\n\n"
        "安装包\n{{file_names}}\n\n"
        "{{summary}}\n通知时间：{{time}}（北京时间）"
    ),
    "button_text": "打开下载页面",
    "header_color": "green",
}
VARIABLES = [
    {"name": "app_name", "label": "应用名称", "sample": "Joice"},
    {"name": "version", "label": "Release 版本", "sample": "Tag: android-debug-v1.0.0"},
    {
        "name": "buildNumber",
        "label": "App 构建号（versionCode / CFBundleVersion，缺失时为“未获取”）",
        "sample": "42",
    },
    {"name": "file_names", "label": "就绪的安装包（每行一个）", "sample": "Joice-v1.0.0.apk"},
    {"name": "summary", "label": "安装包准备结果", "sample": "已就绪 1/1 个安装包"},
    {"name": "time", "label": "通知时间（北京时间）", "sample": "2026/10/07 15:42"},
]
TOKEN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
LIMITS = {"title": 100, "body": 2000, "button_text": 30}
COLORS = {"blue", "green", "orange", "red", "purple", "grey"}


def validate_template(template):
    names = {v["name"] for v in VARIABLES}
    for field, limit in LIMITS.items():
        value = template.get(field, "")
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise AppError(422, "INVALID_NOTIFICATION_TEMPLATE", "模板文案不能为空或超过长度限制")
        tokens = TOKEN.findall(value)
        rest = TOKEN.sub("", value)
        if "{{" in rest or "}}" in rest or any(name not in names for name in tokens):
            raise AppError(
                422, "INVALID_TEMPLATE_VARIABLE", "模板变量无效，请使用下方列出的 {{变量名}}"
            )
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise AppError(422, "INVALID_NOTIFICATION_TEMPLATE", "模板文案含无效控制字符")
    if template.get("header_color") not in COLORS:
        raise AppError(422, "INVALID_NOTIFICATION_TEMPLATE", "请选择有效的标题颜色")


def sample_card():
    return {
        "title": "Debug 安装包已就绪",
        "summary": "已就绪 1/1 个安装包",
        "app_name": "Joice",
        "mode": "debug",
        "version_label": "Tag: android-debug-v1.0.0",
        "build_number": "42",
        "file_names": ["Joice-v1.0.0.apk"],
        "result": "success",
        "occurred_at": "2026-10-07T07:42:00+00:00",
        "page_url": None,
    }


def render_template(template, card):
    values = {
        "app_name": card.get("app_name") or "应用",
        "version": card.get("version_label") or "未提供版本",
        "buildNumber": card.get("build_number") or "未获取",
        "file_names": "\n".join(card.get("file_names", [])),
        "summary": card["summary"],
        "time": datetime.fromisoformat(card["occurred_at"])
        .astimezone(ZoneInfo("Asia/Shanghai"))
        .strftime("%Y/%m/%d %H:%M"),
    }

    def render(field):
        # A single substitution pass: provider strings are text, never template code.
        value = TOKEN.sub(lambda match: values[match[1]], template[field]).strip()
        limit = LIMITS[field]
        return value if len(value) <= limit else value[: limit - 1] + "…"

    return {
        **card,
        "title": render("title") or card["title"],
        "summary": render("body") or card["summary"],
        "button_text": render("button_text") or "查看安装包",
        "header_color": template["header_color"],
    }


def template_config(db):
    row = db.get(IntegrationState, STATE_KEY)
    return {
        "revision": row.revision if row else 0,
        "template": row.data if row else dict(DEFAULT_TEMPLATE),
        "defaults": dict(DEFAULT_TEMPLATE),
        "variables": VARIABLES,
        "sample": sample_card(),
    }


def apply_release_template(db, card):
    row = db.get(IntegrationState, STATE_KEY)
    return render_template(row.data if row else DEFAULT_TEMPLATE, card)
