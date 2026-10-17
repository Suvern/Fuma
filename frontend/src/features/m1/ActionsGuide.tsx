import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import example from "./github-actions-example.yml?raw";
import type { DTO } from "../../shared/api/http";
import { Button, Disclosure, Input, Panel } from "../../shared/ui/controls";
import { ErrorBox, Loading, Title } from "../../shared/ui/common";

export function Copy({ value, label }: { value: string; label: string }) {
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

export function ActionsGuide({
  appId,
  compact = false,
}: {
  appId: string;
  compact?: boolean;
}) {
  if (compact)
    return (
      <Panel className="actions-quick-guide">
        <div className="section-heading">
          <h2>接入 GitHub Actions</h2>
          <Link to="/docs/github-actions">打开独立接入文档</Link>
        </div>
        <p>先创建规则并绑定 Debug/Release 存储桶，再把接入文档交给 Agent 修改源仓库 workflow。</p>
        <Disclosure title="查看接入步骤与 YAML 示例">
          <ActionsGuide appId={appId} />
        </Disclosure>
      </Panel>
    );
  return (
    <Panel aria-labelledby="actions-setup-title">
      <h2 id="actions-setup-title">接入 GitHub Actions</h2>
      <p>
        <Link to="/docs/github-actions">打开独立接入文档</Link> ·{" "}
        <a href="/api/v1/docs/github-actions">Agent 可读的 Markdown</a>
      </p>
      <p>
        仅保存令牌不会触发通知。需要在源应用仓库完成：构建安装包 → 上传绑定的
        COS 存储桶 → 回调 Fuma。GitHub 只提供 workflow、commit 和 run 的来源审计信息。
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
          修改源仓库 build YAML：给发布 job 配置最小 COS 上传凭证，构建后把安装包和
          manifest 上传到规则对应的 Debug/Release 存储桶，再提交回调。只上传 Actions
          artifact 不会被当前接入读取。
        </li>
        <li>
          运行可信分支 / Tag 的 workflow。回调返回 202 后立即结束步骤；Fuma
          等待整个 run 成功，再缓存文件并通知群。不要在同一次 run 中轮询等待
          Fuma 完成。
        </li>
      </ol>
      <p>
        Fuma 不读取 GitHub Release，也不要求 GitHub Release 写权限；GitHub Actions
        只需能运行 workflow，COS 上传凭证由源仓库自行配置。目标群需已加入机器人。
      </p>
      <Disclosure title="复制 build YAML 示例与修改说明">
        <p>
          这是 Android 完整示例。使用你实际的 JDK、构建命令和 APK
          路径；保存路径必须与 Fuma 规则一致。示例的 main
          触发条件也需按可信分支调整。
        </p>
        <p>
          已有构建流程时，保留构建命令，只需补充 COS 上传和最后的 v2 回调步骤。
          多 job 构建需把文件传到发布 job。IPA 需使用对应的 macOS 构建流程，并将
          文件筛选改为 .ipa；不要创建 GitHub Release。
        </p>
        <Copy value={example} label="复制完整 YAML" />
        <pre tabIndex={0} aria-label="GitHub Actions YAML 示例">
          <code>{example}</code>
        </pre>
      </Disclosure>
      <Disclosure title="接入验证与常见失败">
        <ul>
          <li>
            COS 上传或回调步骤失败：检查 Secret / Variable
            是否存在，令牌和回调是否来自同一规则，规则是否启用，以及
            run、SHA、对象 key 与规则配置是否属于该仓库。
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
            缓存 / 通知失败：检查绑定 COS 对象是否仍存在、对象摘要和 manifest 是否正确，以及机器人及通知群状态。
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
  const markdownPath = `/api/v1/docs/github-actions?rule_id=${encodeURIComponent(rule.id)}`;
  const markdownUrl = new URL(markdownPath, window.location.origin).href;
  const agentInstructions = `请按以下文档修改源仓库的 GitHub Actions workflow。\n\n接入文档：${markdownUrl}\n仓库：${rule.repository_full_name}\nWorkflow：${rule.workflow_path}\n可信分支：${rule.allowed_branches.join(", ") || "未配置"}\n可信 Tag：${rule.allowed_tags.join(", ") || "未配置"}\n文件匹配：${rule.asset_patterns.join(", ")}\nFUMA_CALLBACK_URL：${rule.callback_url}\nFUMA_CI_TOKEN：由管理员填入 GitHub Actions Secret，不写入代码或日志。\n\n保留现有构建环境，将安装包和 manifest 上传到 Fuma 已绑定的 COS channel/prefix 后回调；不要创建 GitHub Release。回调返回 202 后结束该步骤，等待整个 workflow 成功再核对 Fuma 构建事件。`;
  return (
    <>
      <div className="toolbar">
        <Link
          to={`/docs/github-actions?rule_id=${encodeURIComponent(rule.id)}`}
        >
          打开此规则接入文档
        </Link>
        <Copy value={markdownUrl} label="复制文档链接给 Agent" />
        <Copy value={agentInstructions} label="复制完整接入说明" />
      </div>
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
          回调使用 Bearer CI 令牌；字段由 GitHub 上下文和 COS 上传结果生成，不接受任意下载 URL、bucket 或群 ID。
        </p>
        <pre tabIndex={0} aria-label="回调请求格式">
          <code>
            {JSON.stringify(
              {
                schema_version: "2",
                event_id: "github-${run_id}-${run_attempt}",
                app_id: "Fuma App UUID",
                channel: "debug | release",
                build: {
                  version: "1.0.0",
                  build_number: "构建号",
                  commit_sha: "40 位提交 SHA",
                  workflow_run_id: "GitHub run ID",
                  created_at: "ISO-8601 时间",
                },
                object: {
                  key: "绑定 COS 中的对象 key",
                  size: 123456,
                  sha256: "64 位 SHA-256",
                  etag: null,
                  content_type: "application/vnd.android.package-archive",
                },
                manifest: {
                  key: "同目录 manifest.json",
                  sha256: "manifest 的 SHA-256",
                },
              },
              null,
              2,
            )}
          </code>
        </pre>
      </Disclosure>
    </>
  );
}

export function ActionsDocumentationPage() {
  const [params] = useSearchParams();
  const ruleId = params.get("rule_id");
  const path = `/api/v1/docs/github-actions${ruleId ? `?rule_id=${encodeURIComponent(ruleId)}` : ""}`;
  const document = useQuery({
    queryKey: ["actions-documentation", ruleId],
    queryFn: async ({ signal }) => {
      const response = await fetch(path, { signal });
      if (!response.ok)
        throw new Error("接入文档暂时无法读取，请检查规则 ID 或稍后重试。");
      return response.text();
    },
    retry: false,
  });
  return (
    <>
      <Title description="可直接交给修改源仓库的 Agent；无需后台登录，不包含 CI Token。">
        GitHub Actions 接入文档
      </Title>
      <div className="toolbar">
        <a href={path}>打开 Markdown 原文</a>
        <Copy
          value={new URL(path, window.location.origin).href}
          label="复制 Agent 文档链接"
        />
        {document.data && <Copy value={document.data} label="复制完整文档" />}
      </div>
      <ErrorBox error={document.error} />
      {document.isPending && <Loading />}
      {document.error && (
        <Button type="button" onClick={() => void document.refetch()}>
          重新加载
        </Button>
      )}
      {document.data && (
        <Panel>
          <DocumentationArticle text={document.data} />
        </Panel>
      )}
    </>
  );
}

// Render only the small, maintained Markdown subset; never interpret raw HTML.
function DocumentationArticle({ text }: { text: string }) {
  const blocks = text.split(/(```[^\n]*\n[\s\S]*?```)/g).filter(Boolean);
  return (
    <article
      className="integration-article"
      aria-label="GitHub Actions 接入说明"
    >
      {blocks.map((block, i) => {
        if (block.startsWith("```"))
          return (
            <pre tabIndex={0} key={i}>
              <code>
                {block.replace(/^```[^\n]*\n/, "").replace(/```$/, "")}
              </code>
            </pre>
          );
        return (
          <div key={i}>
            {block
              .trim()
              .split(/\n\n+/)
              .filter(Boolean)
              .map((paragraph, j) => {
                if (paragraph.startsWith("# ")) return null;
                if (paragraph.startsWith("## "))
                  return <h2 key={j}>{paragraph.slice(3)}</h2>;
                if (paragraph.startsWith("- "))
                  return (
                    <ul key={j}>
                      {paragraph.split("\n").map((line, k) => (
                        <li key={k}>{line.replace(/^- /, "")}</li>
                      ))}
                    </ul>
                  );
                if (/^1\. /.test(paragraph))
                  return (
                    <ol key={j}>
                      {paragraph.split("\n").map((line, k) => (
                        <li key={k}>{line.replace(/^\d+\. /, "")}</li>
                      ))}
                    </ol>
                  );
                return <p key={j}>{paragraph}</p>;
              })}
          </div>
        );
      })}
    </article>
  );
}
