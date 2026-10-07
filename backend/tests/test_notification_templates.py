import pytest

from app.core.errors import AppError
from app.domains.distribution.notification_templates import (
    DEFAULT_TEMPLATE,
    render_template,
    sample_card,
    validate_template,
)


@pytest.mark.parametrize(
    "value", ["{{secret}}", "{{app_name.__class__}}", "{{app_name", "app}}", " "]
)
def test_template_rejects_unknown_malformed_or_empty_fields(value):
    with pytest.raises(AppError):
        validate_template({**DEFAULT_TEMPLATE, "title": value})


def test_render_escapes_values_single_pass_bounded_and_keeps_destination():
    original = {
        **sample_card(),
        "app_name": "{{secret}} <at id=all>",
        "page_url": "https://example.com/apps/1",
    }
    template = {**DEFAULT_TEMPLATE, "body": "{{app_name}}\n{{file_names}}", "button_text": "下载"}
    validate_template(template)
    card = render_template(template, original)
    assert card["summary"] == "{{secret}} &lt;at id=all&gt;\nJoice-v1.0.0.apk"
    assert card["page_url"] == original["page_url"]
    assert card["sub_button_url"] == original["page_url"]
    assert card["sub_button_text"] == "应用下载页"
    assert card["button_text"] == "下载"
    assert original["summary"] == "已就绪 1/1 个安装包"
    long_card = render_template(
        DEFAULT_TEMPLATE, {**original, "app_name": "大" * 3000, "file_names": ["包" * 3000]}
    )
    assert len(long_card["title"]) == 100
    assert len(long_card["summary"]) == 2000
    assert long_card["summary"].endswith("…")


def test_default_preview_matches_real_render_and_beijing_time():
    validate_template(DEFAULT_TEMPLATE)
    card = render_template(DEFAULT_TEMPLATE, sample_card())
    assert card["title"] == "Joice · 新安装包已就绪"
    assert "**Build**：2026100701" in card["summary"]
    assert card["header_color"] == "green"
    assert "2026/10/07 15:42" in card["summary"]
    assert "Joice-v1.0.0.apk" in card["summary"]


def test_build_number_is_literal_and_missing_value_is_explicit():
    card = {**sample_card(), "build_number": None}
    assert "**Build**：未获取" in render_template(DEFAULT_TEMPLATE, card)["summary"]
    card["build_number"] = "{{app_name}}"
    assert r"**Build**：{{app\_name}}" in render_template(DEFAULT_TEMPLATE, card)["summary"]


def test_markdown_template_keeps_syntax_but_escapes_provider_values():
    template = {
        **DEFAULT_TEMPLATE,
        "body": "**版本**：{{version}}\n[下载](https://example.com)\n{{app_name}}",
    }
    card = render_template(
        template, {**sample_card(), "app_name": "*文本* [链接](https://bad.example) <at id=all>"}
    )
    assert card["body_format"] == "lark_md"
    assert "**版本**" in card["summary"]
    assert "[下载](https://example.com)" in card["summary"]
    assert r"\*文本\* \[链接\]\(https://bad.example\) &lt;at id=all&gt;" in card["summary"]
    assert card["title"] == "*文本* [链接](https://bad.example) <at id=all> · 新安装包已就绪"
