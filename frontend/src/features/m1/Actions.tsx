import { BuildResult } from "./BuildStatus";
import {
  buildStates,
  buildPhases,
  currentBuildPhase,
  buildGuidance,
} from "./build-status";
import { ActionsGuide, RuleConnection } from "./ActionsGuide";
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
import { isGlobalAdmin } from "./permissions";
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
  useSession,
} from "../../shared/ui/common";
export function ActionsPage() {
  const session = useSession();
  const { id = "" } = useParams();
  const filters = useFilters("搜索规则名称…");
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
      <ActionsGuide appId={id} compact />
      {isGlobalAdmin(session.data?.user) ? (
        <Disclosure title={<>＋ 新建分发规则</>} className="panel">
          <RuleForm appId={id} />
        </Disclosure>
      ) : (
        <p className="muted">
          创建 Actions
          规则和选择通知群需管理员操作；你可以维护已绑定此应用的规则。
        </p>
      )}
      <div className="toolbar">
        {filters.search}
        {filters.q && (
          <Button type="button" onClick={filters.reset}>
            清空筛选
          </Button>
        )}
      </div>
      <ErrorBox error={q.error} />
      {q.error && (
        <Button type="button" onClick={() => void q.refetch()}>
          重新加载
        </Button>
      )}
      {q.isPending && <Loading />}
      {q.data?.items.map((rule) => (
        <RuleCard key={rule.id} rule={rule} />
      ))}
      {q.data && !q.data.items.length && (
        <Empty title={filters.q ? "没有匹配的规则" : "尚未配置 Actions 规则"}>
          {filters.q
            ? "请修改规则名称或清空筛选。"
            : "创建规则后，按接入文档修改源仓库 workflow。"}
        </Empty>
      )}
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
  const session = useSession();
  const [token, setToken] = useState("");
  return (
    <>
      {cmd.feedback}
      {token && <OneTimeToken token={token} close={() => setToken("")} />}
      {isGlobalAdmin(session.data?.user) ? (
        <ChatPicker selected={selected} onChange={setSelected} />
      ) : (
        <p className="muted">
          沿用已配置的 {selected.length} 个通知群；更换群聊请联系管理员。
        </p>
      )}
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
      <RuleConnection rule={r} />
      <div className="toolbar">
        <Button
          disabled={cmd.pending}
          onClick={() =>
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
              undefined,
              "轮换后旧令牌立即失效，继续？",
            )
          }
        >
          轮换令牌
        </Button>
        <Button
          disabled={cmd.pending || !r.has_token}
          onClick={() =>
            void cmd.run(
              "token-revoke",
              () =>
                write(
                  "/api/v1/actions-rules/{id}/token/revoke",
                  "post",
                  undefined,
                  { id: r.id, revision: r.revision },
                ),
              undefined,
              undefined,
              "撤销此规则的 CI 令牌？",
            )
          }
        >
          撤销令牌
        </Button>
        <Button
          className="danger"
          disabled={cmd.pending}
          onClick={() =>
            void cmd.run(
              "rule-delete",
              () =>
                write("/api/v1/actions-rules/{id}", "delete", undefined, {
                  id: r.id,
                  revision: r.revision,
                }),
              undefined,
              undefined,
              "删除此规则并撤销令牌？历史事件保留。",
            )
          }
        >
          删除规则
        </Button>
      </div>
    </Panel>
  );
}
export function BuildEventsPage() {
  const { id = "" } = useParams();
  const filters = useFilters("搜索 Run ID 或 Commit SHA…");
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
          <span id="build-state-label">分发结果 / 阶段</span>
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
                {s === "received"
                  ? "待处理"
                  : [
                        "succeeded",
                        "partial_success",
                        "failed",
                        "unknown",
                      ].includes(s)
                    ? buildStates[s]
                    : `处理中 · ${labels[s] ?? s}`}
              </Select.Option>
            ))}
          </Select>
        </label>
        {(filters.q || state) && (
          <Button
            type="button"
            onClick={() => {
              filters.reset();
              setState("");
            }}
          >
            清空筛选
          </Button>
        )}
      </div>
      <p className="muted">
        这里跟踪 Fuma 分发进度；回调已接收不等于 GitHub 构建成功或通知已送达。
      </p>
      <ErrorBox error={q.error} />
      {q.error && (
        <Button type="button" onClick={() => void q.refetch()}>
          重新加载
        </Button>
      )}
      <Table
        className="data-table"
        rowKey="id"
        pagination={false}
        dataSource={q.data?.items ?? []}
        loading={q.isPending}
        empty={
          q.isPending || q.error ? (
            <span />
          ) : (
            <Empty
              title={
                filters.q || state ? "没有匹配的构建事件" : "尚未收到构建回调"
              }
            >
              {filters.q || state ? (
                "请修改条件，或清空筛选后重试。"
              ) : (
                <>
                  <p>完成源仓库接入并运行 workflow 后，可在这里追踪分发。</p>
                  <Link to={`/admin/apps/${id}/actions`}>
                    配置 Actions 规则
                  </Link>{" "}
                  · <Link to="/docs/github-actions">查看接入文档</Link>
                </>
              )}
            </Empty>
          )
        }
        scroll={{ x: "100%" }}
        columns={[
          {
            title: "构建",
            render: (_, event) => (
              <Link to={`/admin/events/${event.id}`}>Run #{event.run_id}</Link>
            ),
          },
          { title: "构建轮次", dataIndex: "run_attempt" },
          { title: "当前阶段", render: (_, event) => currentBuildPhase(event) },
          {
            title: "分发结果",
            dataIndex: "state",
            render: (value) => <BuildResult state={value} />,
          },
          { title: "最近更新", dataIndex: "updated_at", render: date },
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
        <BuildResult state={e.state} />
        <p>{buildGuidance(e)}</p>
        <p className="muted">
          {e.stages.find((s) => s.name === "wait_run")?.state === "succeeded"
            ? "GitHub 构建：已核验通过"
            : "GitHub 构建：请查看等待构建阶段的核验结果"}
        </p>
        <dl>
          <dt>构建轮次</dt>
          <dd>{e.run_attempt}</dd>
          <dt>提交 SHA</dt>
          <dd className="mono">{e.head_sha}</dd>
          <dt>Release ID</dt>
          <dd>{e.release_id}</dd>
        </dl>
        <h2>执行轨迹</h2>
        <ol className="build-timeline">
          {e.stages.map((s) => (
            <li
              key={s.name}
              className={`stage stage-${s.state}`}
              aria-current={s.state === "running" ? "step" : undefined}
            >
              <div className="section-heading">
                <h3>{buildPhases[s.name]}</h3>
                <Status value={s.state} />
              </div>
              <p className="muted">
                {s.started_at ? `开始：${date(s.started_at)}` : "尚未开始"}
                {s.finished_at
                  ? ` · 结束：${date(s.finished_at)}`
                  : s.state === "running"
                    ? " · 正在处理"
                    : ""}
              </p>
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
            </li>
          ))}
        </ol>
        <h2>
          安装包结果（{e.assets.filter((a) => a.state === "ready").length}/
          {e.assets.length} 就绪）
        </h2>
        {!e.assets.length && (
          <p className="muted">尚无安装包处理结果，来源核验后会更新。</p>
        )}
        {e.assets.map((a) => (
          <div className="prose" key={a.asset_id}>
            {a.file_name ?? a.asset_id} <Status value={a.state} />{" "}
            {a.error_code}{" "}
            {a.entry_id && (
              <Link to={`/admin/debug/${a.entry_id}`}>查看条目</Link>
            )}
          </div>
        ))}
        <h2>
          通知结果（{e.deliveries.filter((d) => d.state === "succeeded").length}
          /{e.deliveries.length} 成功）
        </h2>
        {!e.deliveries.length && (
          <p className="muted">尚未生成通知记录；请先检查构建与安装包阶段。</p>
        )}
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
