import { Metric } from "../../shared/ui/controls";
import Select from "@douyinfe/semi-ui-19/lib/es/select";
import Table from "@douyinfe/semi-ui-19/lib/es/table";
import Progress from "@douyinfe/semi-ui-19/lib/es/progress";
import { Panel, Notice, Button } from "../../shared/ui/controls";
import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
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
  size,
  text,
  useCommand,
  useFilters,
  labels,
} from "../../shared/ui/common";
export { Component as SystemPage } from "../system/pages/AdminHomePage";
export function TasksPage() {
  const filters = useFilters("搜索任务类型或资源标识…");
  const [state, setState] = useState("");
  const [kind, setKind] = useState<DTO<"Task">["kind"] | "">("");
  const q = useQuery({
    queryKey: ["tasks", filters.page, filters.q, state, kind],
    queryFn: () =>
      read("/api/v1/tasks", {
        query: {
          page: filters.page,
          q: filters.q,
          ...(state ? { state } : {}),
          ...(kind ? { kind } : {}),
        },
      }),
    refetchInterval: 5000,
  });
  return (
    <>
      <Title>任务中心</Title>
      <div className="toolbar">
        {filters.search}
        <StateFilter
          label="任务类型"
          value={kind}
          onChange={(value) => {
            setKind(value as DTO<"Task">["kind"] | "");
            filters.setPage(1);
          }}
          values={[
            "release_sync",
            "release_import",
            "chat_sync",
            "cache_download",
            "build_event",
            "notification",
            "cache_cleanup",
          ]}
        />
        {(filters.q || state || kind) && (
          <Button
            type="button"
            onClick={() => {
              filters.reset();
              setState("");
              setKind("");
            }}
          >
            清空筛选
          </Button>
        )}
        <StateFilter
          value={state}
          onChange={(value) => {
            setState(value);
            filters.setPage(1);
          }}
          values={[
            "queued",
            "running",
            "succeeded",
            "partial_success",
            "failed",
            "unknown",
          ]}
        />
      </div>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
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
              title={filters.q || state || kind ? "没有匹配的任务" : "暂无任务"}
            >
              {filters.q || state || kind
                ? "请修改搜索条件，或清空筛选后重试。"
                : "执行同步、缓存或通知操作后，可在这里跟踪任务。"}
            </Empty>
          )
        }
        scroll={{ x: 720 }}
        columns={[
          {
            title: "任务",
            render: (_, task) => (
              <Link to={`/admin/tasks/${task.id}`}>
                {labels[task.kind] ?? task.kind}
              </Link>
            ),
          },
          {
            title: "执行阶段",
            dataIndex: "phase",
            render: (value) => labels[value] ?? value,
          },
          {
            title: "状态",
            dataIndex: "state",
            render: (value) => <Status value={value} />,
          },
          {
            title: "进度",
            dataIndex: "progress",
            width: 160,
            render: (value) =>
              value === null ? "—" : <Progress percent={value} showInfo />,
          },
          { title: "创建时间", dataIndex: "created_at", render: date },
        ]}
      />
      <Pager data={q.data} {...filters} />
    </>
  );
}
export function TaskPage() {
  const { id = "" } = useParams();
  const q = useQuery({
    queryKey: ["task", id],
    queryFn: () => read("/api/v1/tasks/{id}", { id }),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.state ?? "")
        ? 2000
        : false,
  });
  const cmd = useCommand();
  if (q.isPending) return <Loading />;
  if (!q.data) return <ErrorBox error={q.error} />;
  const t = q.data;
  return (
    <>
      <Title>{`任务：${labels[t.kind] ?? t.kind}`}</Title>
      <Link to="/admin/tasks">← 所有任务</Link>
      {cmd.feedback}
      <Panel className="panel">
        <Status value={t.state} />
        <h2>{labels[t.phase] ?? (t.phase || "等待执行")}</h2>
        {t.progress !== null && (
          <Progress aria-label="任务进度" percent={t.progress} showInfo />
        )}
        <dl>
          <dt>任务 ID</dt>
          <dd className="mono">{t.id}</dd>
          <dt>尝试次数</dt>
          <dd>{t.attempts}</dd>
          <dt>最近更新</dt>
          <dd>{date(t.updated_at)}</dd>
          <dt>下次检查</dt>
          <dd>{date(t.next_check_at)}</dd>
        </dl>
        {t.error_message && (
          <Notice className="notice error">
            {t.error_code}：{t.error_message}
          </Notice>
        )}
        {t.can_retry && (
          <Button
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run("task-retry", (key) =>
                write("/api/v1/tasks/{id}/retry", "post", undefined, {
                  id,
                  key,
                }),
              )
            }
          >
            重试任务
          </Button>
        )}
      </Panel>
    </>
  );
}
function StateFilter({
  value,
  onChange,
  values,
  label = "状态",
}: {
  value: string;
  onChange: (value: string) => void;
  values: string[];
  label?: string;
}) {
  const labelId = useId();
  return (
    <label>
      <span id={labelId}>{label}</span>
      <Select
        aria-labelledby={labelId}
        style={{ minWidth: 160 }}
        value={value}
        onChange={(value) => onChange(String(value ?? ""))}
      >
        <Select.Option value="">全部</Select.Option>
        {values.map((s) => (
          <Select.Option key={s} value={s}>
            {labels[s] ?? s}
          </Select.Option>
        ))}
      </Select>
    </label>
  );
}
export function NotificationsPage() {
  const filters = useFilters("搜索接收群名称…");
  const [state, setState] = useState("");
  const q = useQuery({
    queryKey: ["notifications", filters.page, filters.q, state],
    queryFn: () =>
      read("/api/v1/notifications", {
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
      <Title description="发送成功表示飞书已接受消息，不表示用户已阅读或安装。">
        通知记录
      </Title>
      <div className="toolbar">
        {filters.search}
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
        <StateFilter
          value={state}
          onChange={(value) => {
            setState(value);
            filters.setPage(1);
          }}
          values={["queued", "sending", "succeeded", "failed", "unknown"]}
        />
      </div>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
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
            <Empty title={filters.q || state ? "没有匹配的通知" : "暂无通知"}>
              {filters.q || state
                ? "请修改搜索条件，或清空筛选后重试。"
                : "发送测试卡片或构建通知后，可在这里查看投递结果。"}
            </Empty>
          )
        }
        scroll={{ x: 640 }}
        columns={[
          {
            title: "通知",
            render: (_, delivery) => (
              <Link to={`/admin/notifications/${delivery.id}`}>
                {delivery.card.title}
              </Link>
            ),
          },
          { title: "接收群", dataIndex: "chat_name" },
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
export function NotificationPage() {
  const { id = "" } = useParams();
  const q = useQuery({
    queryKey: ["notification", id],
    queryFn: () => read("/api/v1/notifications/{id}", { id }),
    refetchInterval: (query) =>
      ["queued", "sending"].includes(query.state.data?.state ?? "")
        ? 2000
        : false,
  });
  const cmd = useCommand();
  const [ack, setAck] = useState(false);
  const [task, setTask] = useState<DTO<"TaskAccepted">>();
  if (q.isPending) return <Loading />;
  if (!q.data) return <ErrorBox error={q.error} />;
  const d = q.data;
  return (
    <>
      <Title>通知详情</Title>
      <Link to="/admin/notifications">← 通知记录</Link>
      {cmd.feedback}
      <TaskNotice task={task} />
      <div className="two-columns">
        <Panel className="panel">
          <h2>{d.chat_name}</h2>
          <Status value={d.state} />
          <dl>
            <dt>尝试次数</dt>
            <dd>{d.attempts}</dd>
            <dt>创建时间</dt>
            <dd>{date(d.created_at)}</dd>
            <dt>飞书消息 ID</dt>
            <dd className="mono">{d.provider_message_id ?? "—"}</dd>
          </dl>
          {d.error_message && (
            <Notice className="notice error">
              {d.error_code}：{d.error_message}
            </Notice>
          )}
          {d.state === "unknown" && (
            <Check
              label="我确认重试可能产生重复通知"
              checked={ack}
              onChange={(e) => setAck(!!e.target.checked)}
            />
          )}
          <Button
            disabled={
              cmd.pending || !d.can_retry || (d.state === "unknown" && !ack)
            }
            onClick={() =>
              void cmd.run(
                `notification-retry-${ack}`,
                (key) =>
                  write(
                    "/api/v1/notifications/{id}/retry",
                    "post",
                    { acknowledge_possible_duplicate: ack },
                    { id, key },
                  ),
                setTask,
              )
            }
          >
            重试发送
          </Button>
          {d.event_id && (
            <p>
              <Link to={`/admin/events/${d.event_id}`}>查看构建事件</Link>
            </p>
          )}
        </Panel>
        <Panel className="panel notification-preview">
          <p className="eyebrow">通知卡片内容</p>
          <h2>{d.card.title}</h2>
          <p>{d.card.summary}</p>
          <p>
            {d.card.app_name} · Debug · {d.card.version_label}
          </p>
          <ul>
            {d.card.file_names.map((name, i) => (
              <li key={`${name}-${i}`}>{name}</li>
            ))}
          </ul>
          <Status value={d.card.result} />
          {d.card.page_url && (
            <p>
              <a href={d.card.page_url}>查看分发页面</a>
            </p>
          )}
        </Panel>
      </div>
    </>
  );
}
export function AuditPage() {
  const filters = useFilters();
  const [action, setAction] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const q = useQuery({
    queryKey: ["audit", filters.page, filters.q, action, since, until],
    queryFn: () =>
      read("/api/v1/audit-events", {
        query: {
          page: filters.page,
          q: filters.q,
          ...(action ? { action } : {}),
          ...(since ? { since: new Date(since).toISOString() } : {}),
          ...(until ? { until: new Date(until).toISOString() } : {}),
        },
      }),
  });
  return (
    <>
      <Title description="查询配置变更、登录、缓存与分发的审计摘要。">
        审计日志
      </Title>
      <div className="toolbar">
        {filters.search}
        <Field
          label="操作类型"
          name="action"
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            filters.setPage(1);
          }}
        />
        <Field
          label="开始时间"
          name="since"
          type="datetime-local"
          value={since}
          onChange={(e) => {
            setSince(e.target.value);
            filters.setPage(1);
          }}
        />
        <Field
          label="结束时间"
          name="until"
          type="datetime-local"
          value={until}
          onChange={(e) => {
            setUntil(e.target.value);
            filters.setPage(1);
          }}
        />
      </div>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      <Table
        className="data-table"
        rowKey="id"
        pagination={false}
        loading={q.isPending}
        dataSource={q.data?.items ?? []}
        empty={<Empty>暂无符合条件的审计记录。</Empty>}
        scroll={{ x: 900 }}
        columns={[
          { title: "时间", dataIndex: "occurred_at", width: 190, render: date },
          { title: "操作者", dataIndex: "actor_kind", width: 110 },
          {
            title: "操作 / 对象",
            width: 250,
            render: (_, event) => (
              <>
                {event.action}
                <small>
                  {event.resource_type} · {event.resource_id}
                </small>
              </>
            ),
          },
          {
            title: "结果",
            dataIndex: "outcome",
            width: 100,
            render: (value) => <Status value={value} />,
          },
          {
            title: "摘要",
            render: (_, event) => (
              <>
                {event.summary}
                <small>请求 {event.request_id}</small>
              </>
            ),
          },
        ]}
      />
      <Pager data={q.data} {...filters} />
    </>
  );
}
export function CachePage() {
  const q = useQuery({
    queryKey: ["cache-settings"],
    queryFn: () => read("/api/v1/settings/cache"),
  });
  if (q.isPending) return <Loading />;
  if (!q.data) return <ErrorBox error={q.error} />;
  return <CacheEditor key={q.data.revision} cache={q.data} />;
}
function CacheEditor({ cache: c }: { cache: DTO<"CacheSettings"> }) {
  const cmd = useCommand();
  const [task, setTask] = useState<DTO<"TaskAccepted">>();
  return (
    <>
      <Title description="文件先缓存至本机磁盘；清理会跳过仍有效的下载授权和正在传输的文件。">
        本地缓存
      </Title>
      {cmd.feedback}
      <TaskNotice task={task} />
      <Panel className="panel">
        <div className="health-grid">
          <Metric title="已使用" value={size(c.used_bytes)} />
          <Metric title="已预留" value={size(c.reserved_bytes)} />
          <Metric title="磁盘可用" value={size(c.free_disk_bytes)} />
          <Metric title="活动租约" value={c.active_leases} />
        </div>
        <Form
          submit={(f) =>
            void cmd.run("cache-settings", () =>
              write(
                "/api/v1/settings/cache",
                "put",
                {
                  max_file_bytes: Number(text(f, "max_file_bytes")),
                  budget_bytes: Number(text(f, "budget_bytes")),
                  idle_ttl_seconds: Number(text(f, "idle_ttl_seconds")),
                  grant_ttl_seconds: Number(text(f, "grant_ttl_seconds")),
                  download_concurrency: Number(text(f, "download_concurrency")),
                },
                { revision: c.revision },
              ),
            )
          }
        >
          <Field
            label="单文件上限（字节）"
            name="max_file_bytes"
            type="number"
            min={1}
            max={4294967296}
            defaultValue={c.max_file_bytes}
            required
          />
          <Field
            label="缓存总预算（字节）"
            name="budget_bytes"
            type="number"
            min={1}
            defaultValue={c.budget_bytes}
            required
          />
          <Field
            label="闲置缓存保留时长（秒）"
            name="idle_ttl_seconds"
            type="number"
            min={60}
            defaultValue={c.idle_ttl_seconds}
            required
          />
          <Field
            label="临时下载链接有效期（秒）"
            name="grant_ttl_seconds"
            type="number"
            min={60}
            max={900}
            defaultValue={c.grant_ttl_seconds}
            required
          />
          <Field
            label="下载并发数"
            name="download_concurrency"
            type="number"
            min={1}
            max={8}
            defaultValue={c.download_concurrency}
            required
          />
          <Button className="primary" disabled={cmd.pending}>
            保存缓存策略
          </Button>
        </Form>
        <div className="toolbar">
          <Button
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run(
                "cleanup-expired",
                (key) =>
                  write(
                    "/api/v1/system/cache/cleanup",
                    "post",
                    { scope: "expired" },
                    { key },
                  ),
                setTask,
              )
            }
          >
            清理过期缓存
          </Button>
          <Button
            className="danger"
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run(
                "cleanup-all",
                (key) =>
                  write(
                    "/api/v1/system/cache/cleanup",
                    "post",
                    { scope: "all_unleased" },
                    { key },
                  ),
                setTask,
                undefined,
                "清理全部无活动租约的缓存？下一次下载需要重新缓存。",
              )
            }
          >
            清理可释放缓存
          </Button>
        </div>
      </Panel>
    </>
  );
}
