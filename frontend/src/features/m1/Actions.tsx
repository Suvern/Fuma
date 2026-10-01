import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { ChatPicker } from "./Feishu";
import {
  Check,
  Empty,
  ErrorBox,
  Field,
  Form,
  Loading,
  Pager,
  Status,
  TaskNotice,
  Title,
  date,
  lines,
  text,
  useCommand,
  useFilters,
  labels,
} from "../../shared/ui/common";
export function ActionsPage() {
  const { id = "" } = useParams();
  const filters = useFilters();
  const q = useQuery({
    queryKey: ["rules", id, filters.page, filters.q],
    queryFn: () =>
      read("/api/v1/apps/{id}/actions-rules", {
        id,
        query: { page: filters.page, q: filters.q },
      }),
  });
  return (
    <>
      <Title description="只接受可信仓库、workflow 和 ref 的回调；构建结束且文件就绪后通知所选群。">
        GitHub Actions
      </Title>
      <nav className="tabs">
        <Link to={`/admin/apps/${id}`}>应用设置</Link>
        <Link to={`/admin/apps/${id}/events`}>查看构建事件</Link>
      </nav>
      <details className="panel">
        <summary>＋ 新建分发规则</summary>
        <RuleForm appId={id} />
      </details>
      {filters.search}
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.data?.items.map((rule) => (
        <RuleCard key={rule.id} rule={rule} />
      ))}
      {q.data && !q.data.items.length && <Empty>尚未配置 Actions 规则。</Empty>}
      <Pager data={q.data} {...filters} />
    </>
  );
}
function OneTimeToken({ token, close }: { token: string; close: () => void }) {
  const [copyStatus, setCopyStatus] = useState("");
  return (
    <div role="status" className="notice">
      <strong>令牌仅显示一次</strong>
      <p>
        复制到 GitHub Actions Secret
        FUMA_CI_TOKEN。页面关闭后无法再次查看；不要写入仓库或日志。
      </p>
      <input
        aria-label="一次性 CI 令牌"
        type="password"
        readOnly
        value={token}
        onFocus={(e) => e.target.select()}
      />
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard.writeText(token).then(
            () => setCopyStatus("已复制，请保存在 GitHub Secret 中。"),
            () =>
              setCopyStatus("浏览器未允许复制，请选择令牌输入框后手动复制。"),
          );
        }}
      >
        复制令牌
      </button>
      {copyStatus && <p role="status">{copyStatus}</p>}
      <button type="button" onClick={close}>
        已保存，隐藏令牌
      </button>
    </div>
  );
}
function RuleForm({
  appId,
  rule,
}: {
  appId: string;
  rule?: DTO<"ActionsRule">;
}) {
  const cmd = useCommand();
  const [selected, setSelected] = useState(rule?.chat_ids ?? []);
  const [token, setToken] = useState("");
  return (
    <>
      {cmd.feedback}
      {token && <OneTimeToken token={token} close={() => setToken("")} />}
      <ChatPicker selected={selected} onChange={setSelected} />
      <Form
        submit={(f) => {
          const body: DTO<"ActionsRuleCreate"> = {
            name: text(f, "name"),
            workflow_path: text(f, "workflow_path"),
            allowed_branches: lines(f, "allowed_branches"),
            allowed_tags: lines(f, "allowed_tags"),
            asset_patterns: lines(f, "asset_patterns"),
            chat_ids: selected,
            enabled: f.has("enabled"),
          };
          void cmd.run(
            "rule-save",
            async () => {
              if (rule) {
                await write("/api/v1/actions-rules/{id}", "patch", body, {
                  id: rule.id,
                  revision: rule.revision,
                });
                return undefined;
              }
              return write("/api/v1/apps/{id}/actions-rules", "post", body, {
                id: appId,
              });
            },
            (result) => {
              if (result) setToken(result.token);
            },
          );
        }}
      >
        <Field
          name="name"
          label="规则名称"
          defaultValue={rule?.name}
          required
          maxLength={100}
        />
        <Field
          name="workflow_path"
          label="Workflow 路径"
          defaultValue={rule?.workflow_path ?? ".github/workflows/build.yml"}
          required
          pattern="\.github/workflows/[^/]+\.ya?ml"
        />
        <Field
          name="allowed_branches"
          label="可信分支"
          defaultValue={rule?.allowed_branches.join(", ") ?? "main"}
          help="区分大小写的 glob，多个值用逗号分隔；分支与 Tag 至少填写一项。"
        />
        <Field
          name="allowed_tags"
          label="可信 Tag"
          defaultValue={rule?.allowed_tags.join(", ") ?? ""}
        />
        <Field
          name="asset_patterns"
          label="安装包匹配规则"
          defaultValue={rule?.asset_patterns.join(", ") ?? "*.apk, *.ipa"}
          required
        />
        <Check
          label="启用规则"
          name="enabled"
          defaultChecked={rule?.enabled ?? true}
        />
        <button className="primary" disabled={cmd.pending || !selected.length}>
          {rule ? "保存规则" : "创建规则并签发令牌"}
        </button>
      </Form>
      <p className="muted">
        签发令牌需要近期管理员登录。若请求超时，请先刷新规则列表确认结果，再决定是否轮换，避免重复创建。
      </p>
    </>
  );
}
function RuleCard({ rule: r }: { rule: DTO<"ActionsRule"> }) {
  const cmd = useCommand();
  const [token, setToken] = useState("");
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>{r.name}</h2>
        <span className="badge">{r.enabled ? "已启用" : "已停用"}</span>
      </div>
      <p>
        {r.repository_full_name} · {r.workflow_path}
      </p>
      <p className="muted">
        令牌：{r.has_token ? "已签发" : "已撤销"} · {date(r.token_created_at)}
      </p>
      {cmd.feedback}
      {token && <OneTimeToken token={token} close={() => setToken("")} />}
      <details>
        <summary>编辑规则与通知群</summary>
        <RuleForm key={r.revision} appId={r.app_id} rule={r} />
      </details>
      <details>
        <summary>接入信息</summary>
        <label className="field">
          回调 URL
          <input value={r.callback_url} readOnly />
        </label>
        <p>
          在构建流程上传 Release 安装包后 POST 回调，Authorization 使用 Bearer
          CI 令牌。响应 202 后立即结束回调步骤；服务会等待同次 run 成功再下载。
        </p>
        <pre>
          {JSON.stringify(
            {
              repository_id: r.repository_id,
              run_id: "GitHub run ID",
              run_attempt: 1,
              head_sha: "40 位提交 SHA",
              release_id: "Release ID",
              asset_ids: ["Asset ID"],
            },
            null,
            2,
          )}
        </pre>
        <p>
          字段须来自 GitHub Actions 上下文和已上传 Release 的结果，回调不接收
          URL 或群参数。
        </p>
      </details>
      <div className="toolbar">
        <button
          disabled={cmd.pending}
          onClick={() => {
            if (window.confirm("轮换后旧令牌立即失效，继续？"))
              void cmd.run(
                "token-rotate",
                () =>
                  write(
                    "/api/v1/actions-rules/{id}/token/rotate",
                    "post",
                    undefined,
                    { id: r.id, revision: r.revision },
                  ),
                (result) => setToken(result.token),
              );
          }}
        >
          轮换令牌
        </button>
        <button
          disabled={cmd.pending || !r.has_token}
          onClick={() => {
            if (window.confirm("撤销此规则的 CI 令牌？"))
              void cmd.run("token-revoke", () =>
                write(
                  "/api/v1/actions-rules/{id}/token/revoke",
                  "post",
                  undefined,
                  { id: r.id, revision: r.revision },
                ),
              );
          }}
        >
          撤销令牌
        </button>
        <button
          className="danger"
          disabled={cmd.pending}
          onClick={() => {
            if (window.confirm("删除此规则并撤销令牌？历史事件保留。"))
              void cmd.run("rule-delete", () =>
                write("/api/v1/actions-rules/{id}", "delete", undefined, {
                  id: r.id,
                  revision: r.revision,
                }),
              );
          }}
        >
          删除规则
        </button>
      </div>
    </section>
  );
}
export function BuildEventsPage() {
  const { id = "" } = useParams();
  const filters = useFilters();
  const [state, setState] = useState("");
  const q = useQuery({
    queryKey: ["build-events", id, filters.page, filters.q, state],
    queryFn: () =>
      read("/api/v1/apps/{id}/build-events", {
        id,
        query: {
          page: filters.page,
          q: filters.q,
          ...(state ? { state } : {}),
        },
      }),
    refetchInterval: 5000,
  });
  return (
    <>
      <Title>构建事件</Title>
      <Link to={`/admin/apps/${id}/actions`}>← Actions 规则</Link>
      <div className="toolbar">
        {filters.search}
        <label>
          状态
          <select
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              filters.setPage(1);
            }}
          >
            <option value="">全部</option>
            {[
              "received",
              "verifying",
              "waiting_run",
              "caching",
              "notifying",
              "succeeded",
              "partial_success",
              "failed",
              "unknown",
            ].map((s) => (
              <option key={s} value={s}>
                {labels[s] ?? s}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.data?.items.map((e) => (
        <Link
          className="panel list-option"
          to={`/admin/events/${e.id}`}
          key={e.id}
        >
          <span>
            Run #{e.run_id} / Attempt {e.run_attempt}
          </span>
          <Status value={e.state} />
          <span>{date(e.created_at)}</span>
        </Link>
      ))}
      {q.data && !q.data.items.length && <Empty>尚未收到构建回调。</Empty>}
      <Pager data={q.data} {...filters} />
    </>
  );
}
export function BuildEventPage() {
  const { id = "" } = useParams();
  const q = useQuery({
    queryKey: ["build-event", id],
    queryFn: () => read("/api/v1/build-events/{id}", { id }),
    refetchInterval: 5000,
  });
  const cmd = useCommand();
  const [task, setTask] = useState<DTO<"TaskAccepted">>();
  if (q.isPending) return <Loading />;
  if (!q.data) return <ErrorBox error={q.error} />;
  const e = q.data;
  return (
    <>
      <Title>{`构建 #${e.run_id}`}</Title>
      <Link to={`/admin/apps/${e.app_id}/events`}>← 构建事件</Link>
      {cmd.feedback}
      <TaskNotice task={task} />
      <section className="panel">
        <Status value={e.state} />
        <dl>
          <dt>Attempt</dt>
          <dd>{e.run_attempt}</dd>
          <dt>Commit</dt>
          <dd className="mono">{e.head_sha}</dd>
          <dt>Release</dt>
          <dd>{e.release_id}</dd>
        </dl>
        <h2>执行阶段</h2>
        {e.stages.map((s) => (
          <div key={s.name} className="stage">
            <h3>
              <Status value={s.name} />
            </h3>
            <Status value={s.state} />
            {s.error_message && (
              <p>
                {s.error_code}：{s.error_message}
              </p>
            )}
            {e.retryable_stages.includes(s.name) && (
              <button
                disabled={cmd.pending}
                onClick={() =>
                  void cmd.run(
                    `retry-${s.name}`,
                    (key) =>
                      write(
                        "/api/v1/build-events/{id}/retry",
                        "post",
                        { stage: s.name },
                        { id, key },
                      ),
                    setTask,
                  )
                }
              >
                重试此阶段
              </button>
            )}
          </div>
        ))}
        <h2>安装包结果</h2>
        {e.assets.map((a) => (
          <p key={a.asset_id}>
            {a.file_name ?? a.asset_id} <Status value={a.state} />{" "}
            {a.error_code}{" "}
            {a.entry_id && (
              <Link to={`/admin/debug/${a.entry_id}`}>查看条目</Link>
            )}
          </p>
        ))}
        <h2>通知结果</h2>
        {e.deliveries.map((d) => (
          <p key={d.id}>
            <Link to={`/admin/notifications/${d.id}`}>{d.chat_name}</Link>{" "}
            <Status value={d.state} />
          </p>
        ))}
      </section>
    </>
  );
}
