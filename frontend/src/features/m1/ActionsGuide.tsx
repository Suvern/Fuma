import { useState } from "react";
import { Link } from "react-router";
import example from "./github-actions-example.yml?raw";
import type { DTO } from "../../shared/api/http";
import { Button, Disclosure, Input, Panel } from "../../shared/ui/controls";

function Copy({ value, label }: { value: string; label: string }) {
  const [status, setStatus] = useState("");
  return (
    <>
      <Button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setStatus("已复制。");
          } catch {
            setStatus("无法自动复制，请选择下方内容后手动复制。");
          }
        }}
      >
        {label}
      </Button>
      <span role="status">{status}</span>
    </>
  );
}

export function ActionsGuide({ appId }: { appId: string }) {
  return (
    <Panel aria-labelledby="actions-setup-title">
      <h2 id="actions-setup-title">接入 GitHub Actions</h2>
      <p>
        仅保存令牌不会触发通知。需要在源应用仓库完成：构建安装包 → 上传 GitHub
        Release 附件 → 回调 Fuma。
      </p>
      <ol>
        <li>
          在 Fuma 创建并启用分发规则，选择通知群；仓库、Workflow 路径、可信分支
          / Tag 和安装包匹配规则必须与实际构建一致。
        </li>
        <li>
          在源仓库 Settings → Secrets and variables → Actions → Secrets 新增{" "}
          <code>FUMA_CI_TOKEN</code>，填写规则签发的令牌。
        </li>
        <li>
          在同一位置的 Variables 新增 <code>FUMA_CALLBACK_URL</code>
          ，填写下方对应规则的回调 URL。多条规则应分别使用对应的令牌和 URL。
        </li>
        <li>
          修改源仓库 build YAML：授予发布 job <code>contents: write</code>
          ，构建后上传 Release 附件，再提交回调。只上传 Actions artifact
          不会被当前接入读取。
        </li>
        <li>
          运行可信分支 / Tag 的 workflow。回调返回 202 后立即结束步骤；Fuma
          等待整个 run 成功，再缓存文件并通知群。不要在同一次 run 中轮询等待
          Fuma 完成。
        </li>
      </ol>
      <p>
        Fuma 的 GitHub 连接需要 Contents 与 Actions 读取权限；Release
        写权限由源仓库的 GITHUB_TOKEN 提供。目标群需已加入机器人。
      </p>
      <Disclosure title="复制 build YAML 示例与修改说明">
        <p>
          这是 Android 完整示例。使用你实际的 JDK、构建命令和 APK
          路径；保存路径必须与 Fuma 规则一致。示例的 main
          触发条件也需按可信分支调整。
        </p>
        <p>
          已有构建流程时，合并 permissions 和最后一个步骤即可。已有 Release
          上传步骤时，复用它返回的 Release / asset IDs，再执行回调，避免重复创建
          Release。多 job 构建需把文件传到发布 job。IPA 需使用对应的 macOS
          构建流程，并将附件筛选改为 .ipa。
        </p>
        <Copy value={example} label="复制完整 YAML" />
        <pre tabIndex={0} aria-label="GitHub Actions YAML 示例">
          <code>{example}</code>
        </pre>
      </Disclosure>
      <Disclosure title="接入验证与常见失败">
        <ul>
          <li>
            GitHub 回调步骤失败：检查 Secret / Variable
            是否存在，令牌和回调是否来自同一规则，规则是否启用，以及
            run、SHA、Release 与附件是否属于该仓库。
          </li>
          <li>
            202
            只表示事件已接收，不等于已发卡片。进入构建事件查看来源验证、等待构建、缓存和通知的具体结果。
          </li>
          <li>
            一直等待构建：检查整个 workflow 是否仍运行或失败，回调步骤后不要等待
            Fuma 的最终状态。
          </li>
          <li>
            缓存 / 通知失败：检查 GitHub
            读取权限、附件是否仍存在、机器人及通知群状态。
          </li>
          <li>
            fork PR 无法使用仓库 Secret
            时，不要绕过隔离；从已配置的可信分支触发发布流程。
          </li>
        </ul>
        <Link to={`/admin/apps/${appId}/events`}>查看构建事件</Link>
      </Disclosure>
    </Panel>
  );
}

export function RuleConnection({ rule }: { rule: DTO<"ActionsRule"> }) {
  return (
    <Disclosure title="接入信息：回调 URL 与规则要求">
      <p>
        将此地址保存为源仓库 Actions Variable <code>FUMA_CALLBACK_URL</code>
        。对应令牌保存为 Secret <code>FUMA_CI_TOKEN</code>。
      </p>
      <label>
        回调 URL
        <Input value={rule.callback_url} readOnly />
      </label>
      <Copy value={rule.callback_url} label="复制回调 URL" />
      <dl>
        <dt>仓库</dt>
        <dd>{rule.repository_full_name}</dd>
        <dt>Workflow 路径</dt>
        <dd>
          <code>{rule.workflow_path}</code>
        </dd>
        <dt>可信分支</dt>
        <dd>{rule.allowed_branches.join(", ") || "未配置"}</dd>
        <dt>可信 Tag</dt>
        <dd>{rule.allowed_tags.join(", ") || "未配置"}</dd>
        <dt>文件匹配</dt>
        <dd>{rule.asset_patterns.join(", ")}</dd>
      </dl>
      <p>
        回调使用 Bearer CI 令牌；字段由 GitHub 上下文和 Release
        上传结果生成，不接受任意下载 URL 或群 ID。
      </p>
      <pre tabIndex={0} aria-label="回调请求格式">
        <code>
          {JSON.stringify(
            {
              repository_id: rule.repository_id,
              run_id: "GitHub run ID",
              run_attempt: 1,
              head_sha: "40 位提交 SHA",
              release_id: "Release ID",
              asset_ids: ["Asset ID"],
            },
            null,
            2,
          )}
        </code>
      </pre>
    </Disclosure>
  );
}
