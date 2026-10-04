"""Public, agent-readable instructions; never look up private rule data."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["Integration documentation"])


class MarkdownResponse(PlainTextResponse):
    media_type = "text/markdown"


@router.get(
    "/docs/github-actions",
    response_class=MarkdownResponse,
    operation_id="get_github_actions_document",
    summary="GitHub Actions 接入说明（无需登录，不含凭据或规则私有信息）",
)
def github_actions_documentation(request: Request, rule_id: UUID | None = None) -> str:
    origin = request.app.state.settings.site_url.rstrip("/")
    callback = f"{origin}/api/v1/integrations/github-actions/{rule_id or '<RULE_ID>'}/events"
    example = (Path(__file__).parents[1] / "resources/github-actions-example.yml").read_text()
    hint = (
        "此地址已包含你提供的规则 ID。它不是授权凭据；"
        "仍须使用同一规则签发的 CI Token。文档不验证该规则是否存在或启用。"
        if rule_id
        else "请从 Fuma 的对应规则复制完整地址，替换 <RULE_ID>。不要猜测规则 ID。"
    )
    template = (Path(__file__).parents[1] / "resources/github-actions-guide.md").read_text()
    return (
        template.replace("{{CALLBACK_URL}}", callback)
        .replace("{{RULE_HINT}}", hint)
        .replace("{{WORKFLOW_EXAMPLE}}", example.rstrip())
    )
