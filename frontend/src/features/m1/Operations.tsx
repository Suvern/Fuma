import { useState } from "react";
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
export function SystemPage() {
  const q = useQuery({
    queryKey: ["system-health"],
    queryFn: () => read("/api/v1/system/health"),
    refetchInterval: 10000,
  });
  return (
    <>
      <Title description="从应用配置到 Debug 分发，查看本地服务与异步任务的运行状态。">
        工作台
      </Title>
      <div className="card-grid">
        <Link className="panel app-card" to="/admin/apps">
          <h2>应用管理</h2>
          <p>配置平台、仓库及安装包。</p>
        </Link>
        <Link className="panel app-card" to="/admin/connectors">
          <h2>GitHub Connector</h2>
          <p>配置凭据并验证仓库读取权限。</p>
        </Link>
        <Link className="panel app-card" to="/admin/settings/feishu">
          <h2>飞书与机器人</h2>
          <p>验证租户，选择通知群聊。</p>
        </Link>
      </div>
      <section className="panel">
        <div className="section-heading">
          <h2>服务运行状态</h2>
          <button onClick={() => void q.refetch()} disabled={q.isFetching}>
            刷新
          </button>
        </div>
        <ErrorBox error={q.error} />
        {q.isPending && <Loading />}
        {q.data && (
          <>
            <div className="health-grid">
              {(
                ["api", "database", "redis", "worker", "scheduler"] as const
              ).map((k) => (
                <div key={k}>
                  <h3>{k}</h3>
                  <Status value={q.data[k]} />
                </div>
              ))}
            </div>
            <dl>
              <dt>外部访问地址</dt>
              <dd>{q.data.public_origin}</dd>
              <dt>Worker 最近心跳</dt>
              <dd>{date(q.data.worker_last_seen_at)}</dd>
              <dt>缓存可写</dt>
              <dd>{q.data.cache_writable ? "是" : "否"}</dd>
              <dt>磁盘可用空间</dt>
              <dd>{size(q.data.cache_free_bytes)}</dd>
            </dl>
          </>
        )}
      </section>
    </>
  );
}
export function TasksPage() {
  const filters = useFilters();
  const [state, setState] = useState("");
  const q = useQuery({
    queryKey: ["tasks", filters.page, filters.q, state],
    queryFn: () =>
      read("/api/v1/tasks", {
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
      <Title>任务中心</Title>
      <div className="toolbar">
        {filters.search}
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
      {q.data?.items.map((t) => (
        <Link
          className="panel list-option"
          key={t.id}
          to={`/admin/tasks/${t.id}`}
        >
          <span>
            {labels[t.kind] ?? t.kind} · {labels[t.phase] ?? t.phase}
          </span>
          <Status value={t.state} />
          <span>{t.progress === null ? "—" : `${t.progress}%`}</span>
          <span>{date(t.created_at)}</span>
        </Link>
      ))}
      {q.data && !q.data.items.length && <Empty>暂无任务。</Empty>}
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
      <section className="panel">
        <Status value={t.state} />
        <h2>{labels[t.phase] ?? (t.phase || "等待执行")}</h2>
        {t.progress !== null && <progress value={t.progress} max={100} />}
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
          <p className="notice error">
            {t.error_code}：{t.error_message}
          </p>
        )}
        {t.can_retry && (
          <button
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
          </button>
        )}
      </section>
    </>
  );
}
function StateFilter({
  value,
  onChange,
  values,
}: {
  value: string;
  onChange: (value: string) => void;
  values: string[];
}) {
  return (
    <label>
      状态
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">全部</option>
        {values.map((s) => (
          <option key={s} value={s}>
            {labels[s] ?? s}
          </option>
        ))}
      </select>
    </label>
  );
}
export function NotificationsPage() {
  const filters = useFilters();
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
      {q.data?.items.map((d) => (
        <Link
          key={d.id}
          className="panel list-option"
          to={`/admin/notifications/${d.id}`}
        >
          <span>
            {d.card.title} · {d.chat_name}
          </span>
          <Status value={d.state} />
          <span>{date(d.created_at)}</span>
        </Link>
      ))}
      {q.data && !q.data.items.length && <Empty>暂无通知。</Empty>}
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
        <section className="panel">
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
            <p className="notice error">
              {d.error_code}：{d.error_message}
            </p>
          )}
          {d.state === "unknown" && (
            <Check
              label="我确认重试可能产生重复通知"
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
            />
          )}
          <button
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
          </button>
          {d.event_id && (
            <p>
              <Link to={`/admin/events/${d.event_id}`}>查看构建事件</Link>
            </p>
          )}
        </section>
        <section className="panel notification-preview">
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
        </section>
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
      <div className="table-wrap panel">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>操作者</th>
              <th>操作 / 对象</th>
              <th>结果</th>
              <th>摘要</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.items.map((e) => (
              <tr key={e.id}>
                <td>{date(e.occurred_at)}</td>
                <td>{e.actor_kind}</td>
                <td>
                  {e.action}
                  <small>
                    {e.resource_type} · {e.resource_id}
                  </small>
                </td>
                <td>
                  <Status value={e.outcome} />
                </td>
                <td>
                  {e.summary}
                  <small>请求 {e.request_id}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.data && !q.data.items.length && (
          <Empty>暂无符合条件的审计记录。</Empty>
        )}
      </div>
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
      <section className="panel">
        <div className="health-grid">
          <div>
            <h3>已使用</h3>
            {size(c.used_bytes)}
          </div>
          <div>
            <h3>已预留</h3>
            {size(c.reserved_bytes)}
          </div>
          <div>
            <h3>磁盘可用</h3>
            {size(c.free_disk_bytes)}
          </div>
          <div>
            <h3>活动租约</h3>
            {c.active_leases}
          </div>
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
          <button className="primary" disabled={cmd.pending}>
            保存缓存策略
          </button>
        </Form>
        <div className="toolbar">
          <button
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
          </button>
          <button
            className="danger"
            disabled={cmd.pending}
            onClick={() => {
              if (
                window.confirm(
                  "清理全部无活动租约的缓存？下一次下载需要重新缓存。",
                )
              )
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
                );
            }}
          >
            清理可释放缓存
          </button>
        </div>
      </section>
    </>
  );
}
