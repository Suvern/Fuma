import { confirmAction } from "../../shared/ui/confirm";
import Select from "@douyinfe/semi-ui-19/lib/es/select";
import Table from "@douyinfe/semi-ui-19/lib/es/table";
import {
  PageTabs,
  Disclosure,
  Notice,
  Input,
  Button,
  Panel,
  Badge,
} from "../../shared/ui/controls";
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
      <PageTabs className="tabs">
        <Link to={`/admin/apps/${id}`}>应用设置</Link>
        <Link to={`/admin/apps/${id}/events`}>查看构建事件</Link>
      </PageTabs>
      <Disclosure title={<>＋ 新建分发规则</>} className="panel">
        <RuleForm appId={id} />
      </Disclosure>
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
    <Notice role="status" className="notice">
      <strong>令牌仅显示一次</strong>
      <p>
        复制到 GitHub Actions Secret
        FUMA_CI_TOKEN。页面关闭后无法再次查看；不要写入仓库或日志。
      </p>
      <Input
        aria-label="一次性 CI 令牌"
        type="password"
        readOnly
        value={token}
        onFocus={(e) => e.target.select()}
      />
      <Button
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
      </Button>
      {copyStatus && <p role="status">{copyStatus}</p>}
      <Button type="button" onClick={close}>
        已保存，隐藏令牌
      </Button>
    </Notice>
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
          pattern={String.raw`\.github/workflows/[^\/]+\.ya?ml`}
          validationMessage="请填写 .github/workflows/ 下的 .yml 或 .yaml 文件路径。"
          help="例如 .github/workflows/build.yml。"
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
        <Button className="primary" disabled={cmd.pending || !selected.length}>
          {rule ? "保存规则" : "创建规则并签发令牌"}
        </Button>
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
    <Panel className="panel">
      <div className="section-heading">
        <h2>{r.name}</h2>
        <Badge className="badge">{r.enabled ? "已启用" : "已停用"}</Badge>
      </div>
      <p>
        {r.repository_full_name} · {r.workflow_path}
      </p>
      <p className="muted">
        令牌：{r.has_token ? "已签发" : "已撤销"} · {date(r.token_created_at)}
      </p>
      {cmd.feedback}
      {token && <OneTimeToken token={token} close={() => setToken("")} />}
      <Disclosure title={<>编辑规则与通知群</>}>
        <RuleForm key={r.revision} appId={r.app_id} rule={r} />
      </Disclosure>
      <Disclosure title={<>接入信息</>}>
        <label className="field">
          回调 URL
          <Input value={r.callback_url} readOnly />
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
      </Disclosure>
      <div className="toolbar">
        <Button
          disabled={cmd.pending}
          onClick={async () => {
            if (await confirmAction("轮换后旧令牌立即失效，继续？"))
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
        </Button>
        <Button
          disabled={cmd.pending || !r.has_token}
          onClick={async () => {
            if (await confirmAction("撤销此规则的 CI 令牌？"))
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
        </Button>
        <Button
          className="danger"
          disabled={cmd.pending}
          onClick={async () => {
            if (await confirmAction("删除此规则并撤销令牌？历史事件保留。"))
              void cmd.run("rule-delete", () =>
                write("/api/v1/actions-rules/{id}", "delete", undefined, {
                  id: r.id,
                  revision: r.revision,
                }),
              );
          }}
        >
          删除规则
        </Button>
      </div>
    </Panel>
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
      <PageTabs />
      <div className="toolbar">
        {filters.search}
        <label>
          <span id="build-state-label">状态</span>
          <Select
            aria-labelledby="build-state-label"
            style={{ minWidth: 160 }}
            value={state}
            onChange={(value) => {
              setState(String(value ?? ""));
              filters.setPage(1);
            }}
          >
            <Select.Option value="">全部</Select.Option>
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
              <Select.Option key={s} value={s}>
                {labels[s] ?? s}
              </Select.Option>
            ))}
          </Select>
        </label>
      </div>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      <Table
        className="data-table"
        rowKey="id"
        pagination={false}
        dataSource={q.data?.items ?? []}
        loading={q.isPending}
        empty={<Empty>尚未收到构建回调。</Empty>}
        scroll={{ x: 640 }}
        columns={[
          {
            title: "构建",
            render: (_, event) => (
              <Link to={`/admin/events/${event.id}`}>Run #{event.run_id}</Link>
            ),
          },
          { title: "尝试次数", dataIndex: "run_attempt" },
          {
            title: "状态",
            dataIndex: "state",
            render: (value) => <Status value={value} />,
          },
          { title: "创建时间", dataIndex: "created_at", render: date },
        ]}
      />
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
      <Panel className="panel">
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
              <Button
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
              </Button>
            )}
          </div>
        ))}
        <h2>安装包结果</h2>
        {e.assets.map((a) => (
          <div className="prose" key={a.asset_id}>
            {a.file_name ?? a.asset_id} <Status value={a.state} />{" "}
            {a.error_code}{" "}
            {a.entry_id && (
              <Link to={`/admin/debug/${a.entry_id}`}>查看条目</Link>
            )}
          </div>
        ))}
        <h2>通知结果</h2>
        {e.deliveries.map((d) => (
          <div className="prose" key={d.id}>
            <Link to={`/admin/notifications/${d.id}`}>{d.chat_name}</Link>{" "}
            <Status value={d.state} />
          </div>
        ))}
      </Panel>
    </>
  );
}
