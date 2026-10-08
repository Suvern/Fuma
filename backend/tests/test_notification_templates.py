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


def test_render_is_plain_text_single_pass_bounded_and_keeps_destination():
    original = {
        **sample_card(),
        "app_name": "{{secret}} <at id=all>",
        "page_url": "https://example.com/apps/1",
    }
    template = {**DEFAULT_TEMPLATE, "body": "{{app_name}}\n{{file_names}}", "button_text": "下载"}
    validate_template(template)
    card = render_template(template, original)
    assert card["summary"] == "{{secret}} <at id=all>\nSomeProject-v1.0.0.apk"
    assert card["page_url"] == original["page_url"]
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
    assert card["title"] == "SomeProject · 新安装包已就绪"
    assert "Build：42" in card["summary"]
    assert card["header_color"] == "green"
    assert "2026/10/07 15:42" in card["summary"]
    assert "SomeProject-v1.0.0.apk" in card["summary"]


def test_build_number_is_literal_and_missing_value_is_explicit():
    card = {**sample_card(), "build_number": None}
    assert "Build：未获取" in render_template(DEFAULT_TEMPLATE, card)["summary"]
    card["build_number"] = "{{app_name}}"
    assert "Build：{{app_name}}" in render_template(DEFAULT_TEMPLATE, card)["summary"]
