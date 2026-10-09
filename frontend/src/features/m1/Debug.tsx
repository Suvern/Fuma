import { LegacyPersistence } from "../library/GitHubImport";
import Select from "@douyinfe/semi-ui-19/lib/es/select";
import List from "@douyinfe/semi-ui-19/lib/es/list";
import Progress from "@douyinfe/semi-ui-19/lib/es/progress";
import {
  PageTabs,
  CardLink,
  Badge,
  Panel,
  Notice,
  Button,
  Disclosure,
} from "../../shared/ui/controls";
import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { DownloadGuard } from "./Auth";
import { AppIcon } from "./AppIcon";
import { Icon } from "../../shared/ui/Icon";
import "./catalog.css";
import { SharePage } from "../../shared/ui/SharePage";
import {
  Check,
  Empty,
  ErrorBox,
  Loading,
  Pager,
  Status,
  TaskNotice,
  Title,
  date,
  size,
  useCommand,
  useFilters,
  useSession,
} from "../../shared/ui/common";
type EntrySort = "source_updated_at" | "imported_at";
function EntrySortPicker({
  value,
  onChange,
  disabled,
}: {
  value: EntrySort;
  onChange: (value: EntrySort) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  return (
    <label className="filter-field">
      <span id={labelId}>排序</span>
      <Select
        aria-labelledby={labelId}
        disabled={disabled}
        style={{ minWidth: 200 }}
        value={value}
        onChange={(next) => onChange(next as EntrySort)}
      >
        <Select.Option value="source_updated_at">
          来源更新时间从新到旧
        </Select.Option>
        <Select.Option value="imported_at">导入时间从新到旧</Select.Option>
      </Select>
    </label>
  );
}
type BatchAction = "cache" | "enable" | "disable";
type BatchItemResult = {
  id: string;
  name: string;
  state: "success" | "skipped" | "failed";
  task?: DTO<"TaskAccepted">;
  error?: unknown;
  reason?: string;
};
const cachingStates = ["queued", "downloading", "verifying"];
const batchLabels = {
  cache: "批量缓存",
  enable: "批量启用",
  disable: "批量停用",
};

export function DebugListPage() {
  const { id = "" } = useParams();
  const filters = useFilters("搜索文件名、Tag 或版本…");
  const [sort, setSort] = useState<EntrySort>("source_updated_at");
  const cmd = useCommand();
  const scope = JSON.stringify([id, filters.page, filters.q, sort]);
  const [selection, setSelection] = useState<{ scope: string; ids: string[] }>({
    scope,
    ids: [],
  });
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [report, setReport] = useState<{
    scope: string;
    action: BatchAction;
    items: BatchItemResult[];
  }>();
  const cacheKeys = useRef(new Map<string, string>());
  const selectAllRef = useRef<HTMLSpanElement>(null);
  if (selection.scope !== scope) {
    setSelection({ scope, ids: [] });
    setReport(undefined);
  }

  const q = useQuery({
    queryKey: ["debug-list", id, filters.page, filters.q, sort],
    queryFn: () =>
      read("/api/v1/apps/{id}/debug-entries", {
        id,
        query: { page: filters.page, q: filters.q, sort },
      }),
    refetchInterval: (query) =>
      query.state.data?.items.some((entry) =>
        cachingStates.includes(entry.cache.state),
      )
        ? 2500
        : false,
  });
  const entries = q.data?.items ?? [];
  const selected = entries.filter(
    (entry) => selection.scope === scope && selection.ids.includes(entry.id),
  );
  const selectedIds = new Set(selected.map((entry) => entry.id));
  const allSelected = entries.length > 0 && selected.length === entries.length;
  const partlySelected = selected.length > 0 && !allSelected;
  useEffect(() => {
    // Semi renders the mixed icon but does not expose the native mixed state.
    const input = selectAllRef.current?.querySelector("input");
    if (input) {
      input.indeterminate = partlySelected;
      input.setAttribute(
        "aria-checked",
        partlySelected ? "mixed" : String(allSelected),
      );
    }
  }, [allSelected, partlySelected]);
  const currentReport = report?.scope === scope ? report : undefined;
  function select(ids: string[]) {
    if (!cmd.pending) setSelection({ scope, ids });
  }
  function runBatch(action: BatchAction) {
    if (!selected.length || cmd.pending) return;
    const targets = [...selected];
    setProgress({ done: 0, total: 0 });
    void cmd.run(
      `debug-batch-${action}`,
      async () => {
        setReport(undefined);
        setProgress({ done: 0, total: targets.length });
        const results: BatchItemResult[] = new Array(targets.length);
        let next = 0;
        async function worker() {
          while (next < targets.length) {
            const index = next++;
            const entry = targets[index];
            if (!entry) return;
            const result: BatchItemResult = {
              id: entry.id,
              name: entry.file_name,
              state: "success",
            };
            try {
              if (action === "cache") {
                if (
                  entry.cache.state === "ready" ||
                  cachingStates.includes(entry.cache.state)
                ) {
                  result.state = "skipped";
                  result.reason =
                    entry.cache.state === "ready"
                      ? "缓存已就绪"
                      : "已有缓存任务处理中";
                } else {
                  const key =
                    cacheKeys.current.get(entry.id) ?? crypto.randomUUID();
                  cacheKeys.current.set(entry.id, key);
                  result.task = await write(
                    "/api/v1/debug-entries/{id}/precache",
                    "post",
                    undefined,
                    { id: entry.id, key },
                  );
                  cacheKeys.current.delete(entry.id);
                }
              } else if (entry.enabled === (action === "enable")) {
                result.state = "skipped";
                result.reason = entry.enabled ? "已经启用" : "已经停用";
              } else {
                await write(
                  "/api/v1/debug-entries/{id}",
                  "patch",
                  { enabled: action === "enable" },
                  { id: entry.id, revision: entry.revision },
                );
              }
            } catch (error) {
              result.state = "failed";
              result.error = error;
            }
            results[index] = result;
            setProgress((value) => ({ ...value, done: value.done + 1 }));
          }
        }
        await Promise.all(
          Array.from({ length: Math.min(3, targets.length) }, worker),
        );
        return results;
      },
      (items) => {
        setReport({ scope, action, items });
        setSelection({
          scope,
          ids: items
            .filter((item) => item.state === "failed")
            .map((item) => item.id),
        });
      },
      "",
      action === "disable"
        ? `停用所选 ${targets.length} 个 Debug 包的分发？停用后将不再签发新的下载授权，已签发的短期链接仍可能有效。`
        : undefined,
    );
  }
  return (
    <div className="app-tab-page debug-list-page">
      <Title description="查看旧版 Debug 分发包、缓存状态与来源更新。">
        Debug 包管理
      </Title>
      <PageTabs className="tabs">
        <Link to={`/admin/apps/${id}`}>应用设置</Link>
        <Link to={`/admin/apps/${id}/releases`}>从 Release 导入</Link>
      </PageTabs>
      <fieldset className="app-tab-filters" disabled={cmd.pending}>
        {filters.search}
        <EntrySortPicker
          value={sort}
          disabled={cmd.pending}
          onChange={(value) => {
            setSort(value);
            filters.setPage(1);
          }}
        />
        {filters.q && (
          <Button type="button" onClick={filters.reset}>
            清空筛选
          </Button>
        )}
      </fieldset>
      <p className="muted">
        来源更新时间指 GitHub 附件更新时间；缺失时按导入时间排序。
      </p>
      {cmd.feedback}
      {cmd.pending && progress.total > 0 && (
        <div className="debug-batch-progress" role="status">
          <span>
            正在提交批量操作：{progress.done} / {progress.total}
          </span>
          <Progress
            aria-label="批量操作提交进度"
            percent={Math.round((progress.done / progress.total) * 100)}
          />
        </div>
      )}
      {currentReport && (
        <section className="debug-batch-report" aria-label="批量操作结果">
          <div className="section-heading">
            <p role="status">
              {batchLabels[currentReport.action]}：
              {currentReport.action === "cache" ? "已提交" : "成功"}{" "}
              {
                currentReport.items.filter((item) => item.state === "success")
                  .length
              }{" "}
              个，跳过{" "}
              {
                currentReport.items.filter((item) => item.state === "skipped")
                  .length
              }{" "}
              个，失败{" "}
              {
                currentReport.items.filter((item) => item.state === "failed")
                  .length
              }{" "}
              个。
            </p>
            <Button
              type="button"
              disabled={cmd.pending}
              onClick={() => setReport(undefined)}
            >
              关闭结果
            </Button>
          </div>
          <p className="muted">
            {currentReport.action === "cache"
              ? "缓存任务在后台运行，提交成功不代表缓存已完成。"
              : "已完成的条目已取消勾选。"}
            失败项保留勾选，可重试。
          </p>
          <Disclosure title="查看逐项结果">
            <ul className="debug-batch-results">
              {currentReport.items.map((item) => (
                <li key={item.id}>
                  <span className="debug-batch-result-name">{item.name}</span>
                  {item.state === "failed" ? (
                    <ErrorBox error={item.error} />
                  ) : item.reason ? (
                    <span>{item.reason}</span>
                  ) : item.task ? (
                    <Link to={`/admin/tasks/${item.task.task_id}`}>
                      查看缓存任务
                    </Link>
                  ) : (
                    <span>操作成功</span>
                  )}
                </li>
              ))}
            </ul>
          </Disclosure>
        </section>
      )}
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.error && (
        <Button type="button" onClick={() => void q.refetch()}>
          重新加载
        </Button>
      )}
      {q.data && (
        <List
          className="debug-package-list"
          bordered
          size="small"
          dataSource={q.data.items}
          header={
            <div className="debug-batch-header">
              <div className="section-heading">
                <div className="inline">
                  <span ref={selectAllRef}>
                    <Check
                      label="全选当前页"
                      checked={allSelected}
                      indeterminate={partlySelected}
                      disabled={cmd.pending || !entries.length}
                      onChange={(event) =>
                        select(
                          event.target.checked
                            ? entries.map((entry) => entry.id)
                            : [],
                        )
                      }
                    />
                  </span>
                  <span className="muted">
                    共 {q.data.total} 个 · 已选 {selected.length} 个
                  </span>
                </div>
                <Button
                  type="button"
                  disabled={cmd.pending || !selected.length}
                  onClick={() => select([])}
                >
                  取消选择
                </Button>
              </div>
              <div className="debug-batch-actions">
                <Button
                  type="button"
                  className="primary"
                  disabled={cmd.pending || !selected.length}
                  onClick={() => runBatch("cache")}
                >
                  批量缓存 / 重试
                </Button>
                <Button
                  type="button"
                  disabled={cmd.pending || !selected.length}
                  onClick={() => runBatch("enable")}
                >
                  批量启用
                </Button>
                <Button
                  type="button"
                  disabled={cmd.pending || !selected.length}
                  onClick={() => runBatch("disable")}
                >
                  批量停用
                </Button>
              </div>
              <p className="muted">
                仅操作当前页已选项；切换分页、搜索或排序会清空选择。缓存时自动跳过已就绪或处理中的条目。
              </p>
            </div>
          }
          emptyContent={
            <Empty
              title={filters.q ? "没有匹配的 Debug 包" : "暂无 Debug 条目"}
            >
              {filters.q
                ? "请修改或清空搜索条件后重试。"
                : "请从 Release 选择安装包。"}
            </Empty>
          }
          renderItem={(entry) => (
            <List.Item
              key={entry.id}
              className={
                selectedIds.has(entry.id) ? "debug-package-selected" : undefined
              }
            >
              <Check
                className="debug-package-select"
                label=""
                aria-label={`选择 ${entry.file_name}`}
                checked={selectedIds.has(entry.id)}
                disabled={cmd.pending}
                onChange={(event) =>
                  select(
                    event.target.checked
                      ? [...selectedIds, entry.id]
                      : [...selectedIds].filter((value) => value !== entry.id),
                  )
                }
              />
              <div className="debug-package-row">
                <div className="debug-package-main">
                  <Link
                    className="debug-package-name"
                    title={entry.file_name}
                    to={`/admin/debug/${entry.id}`}
                  >
                    {entry.file_name}
                  </Link>
                  <div className="debug-package-meta">
                    <span title={entry.version_name ?? entry.source_tag}>
                      {entry.version_name
                        ? `版本 ${entry.version_name}`
                        : `Tag ${entry.source_tag}`}
                    </span>
                    <span>{size(entry.size_bytes)}</span>
                  </div>
                  <div className="inline debug-package-status">
                    <Status value={entry.platform} />
                    <Status value={entry.cache.state} />
                    <Badge>{entry.enabled ? "已启用" : "已停用"}</Badge>
                  </div>
                </div>
                <div className="debug-package-dates">
                  <span>来源更新：{date(entry.source.asset_updated_at)}</span>
                  <span>导入时间：{date(entry.created_at)}</span>
                </div>
                <Link
                  className="button"
                  aria-label={`查看 ${entry.file_name} 详情`}
                  to={`/admin/debug/${entry.id}`}
                >
                  详情
                </Link>
              </div>
            </List.Item>
          )}
        />
      )}
      <Pager data={q.data} {...filters} disabled={cmd.pending} />
    </div>
  );
}
export function DebugAdminPage() {
  const { id = "" } = useParams();
  const q = useQuery({
    queryKey: ["debug", id],
    queryFn: () => read("/api/v1/debug-entries/{id}", { id }),
    refetchInterval: (query) =>
      ["queued", "downloading", "verifying"].includes(
        query.state.data?.cache.state ?? "",
      )
        ? 2000
        : false,
  });
  const cmd = useCommand();
  const [task, setTask] = useState<DTO<"TaskAccepted">>();
  if (q.isPending) return <Loading />;
  if (!q.data) return <ErrorBox error={q.error} />;
  const e = q.data;
  return (
    <>
      <Title>{e.file_name}</Title>
      <Link to={`/admin/apps/${e.app_id}/debug`}>← Debug 列表</Link>
      {cmd.feedback}
      <TaskNotice task={task} />
      <Panel className="panel">
        <div className="inline">
          <Status value={e.platform} />
          <Status value={e.cache.state} />
          <Badge className="badge">Debug</Badge>
        </div>
        <dl>
          <dt>版本</dt>
          <dd>{e.version_name ?? `来源 Tag：${e.source_tag}`}</dd>
          <dt>构建号</dt>
          <dd>{e.build_number ?? "—"}</dd>
          <dt>文件大小</dt>
          <dd>{size(e.size_bytes)}</dd>
          <dt>来源仓库</dt>
          <dd>{e.source.repository_full_name}</dd>
          <dt>Release / Asset ID</dt>
          <dd>
            {e.source.release_id} / {e.source.asset_id}
          </dd>
          <dt>来源更新时间</dt>
          <dd>{date(e.source.asset_updated_at)}</dd>
          <dt>SHA256</dt>
          <dd className="mono">{e.cache.sha256 ?? "缓存后生成"}</dd>
        </dl>
        {e.cache.error_message && (
          <Notice className="notice error">
            {e.cache.error_code}：{e.cache.error_message}
          </Notice>
        )}
        <div className="toolbar">
          <Button
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run(
                "precache",
                (key) =>
                  write(
                    "/api/v1/debug-entries/{id}/precache",
                    "post",
                    undefined,
                    { id, key },
                  ),
                setTask,
              )
            }
          >
            预缓存 / 重试缓存
          </Button>
          <Button
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run("entry-toggle", () =>
                write(
                  "/api/v1/debug-entries/{id}",
                  "patch",
                  { enabled: !e.enabled },
                  { id, revision: e.revision },
                ),
              )
            }
          >
            {e.enabled ? "停用分发" : "启用分发"}
          </Button>
          <Link className="button" to={`/debug/${id}`}>
            查看分发页面
          </Link>
        </div>
        <p className="muted">
          分享固定分发页面；访问及下载需登录飞书或管理员账号。
        </p>
        <SharePage url={e.page_url} />
      </Panel>
      <LegacyPersistence entry={e} />
    </>
  );
}
export function CatalogPage() {
  return (
    <DownloadGuard>
      <CatalogContent />
    </DownloadGuard>
  );
}
function CatalogContent() {
  const session = useSession();
  const filters = useFilters("搜索应用名称…");
  const q = useQuery({
    queryKey: [
      "catalog-apps",
      session.data?.viewer_key,
      filters.page,
      filters.q,
    ],
    queryFn: () =>
      read("/api/v1/catalog/apps", {
        query: { page: filters.page, q: filters.q },
      }),
  });
  return (
    <>
      <Title description="登录后即可获取团队的最新 Debug 安装包。">
        应用下载
      </Title>
      {filters.search}
      {q.error ? (
        <ErrorBox error={q.error} />
      ) : q.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="card-grid">
            {q.data?.items.map((app) => (
              <CardLink
                to={`/apps/${app.id}`}
                key={app.id}
                className="panel app-card"
              >
                <div className="app-monogram">{app.name[0]}</div>
                <h2>{app.name}</h2>
                <p>{app.description}</p>
                <div className="inline">
                  {app.platforms.map((p) => (
                    <Status key={p} value={p} />
                  ))}
                  <span>{app.debug_entry_count} 个包</span>
                </div>
              </CardLink>
            ))}
          </div>
          {!q.data?.items.length && <Empty>没有可访问的应用。</Empty>}
          <Pager data={q.data} {...filters} />
        </>
      )}
    </>
  );
}
export function CatalogAppPage() {
  return (
    <DownloadGuard>
      <CatalogAppContent />
    </DownloadGuard>
  );
}
function CatalogAppContent() {
  const session = useSession();
  const { id = "" } = useParams();
  const filters = useFilters("搜索文件名、Tag 或版本…");
  const [sort, setSort] = useState<EntrySort>("source_updated_at");
  const [platform, setPlatform] = useState("");
  const app = useQuery({
    queryKey: ["catalog-app", session.data?.viewer_key, id],
    queryFn: () => read("/api/v1/catalog/apps/{id}", { id }),
  });
  const entries = useQuery({
    queryKey: [
      "catalog-entries",
      session.data?.viewer_key,
      id,
      filters.q,
      filters.page,
      platform,
      sort,
    ],
    queryFn: () =>
      read("/api/v1/catalog/debug-entries", {
        query: {
          app_id: id,
          sort,
          page: filters.page,
          q: filters.q,
          ...(platform ? { platform } : {}),
        },
      }),
  });
  const latest = useQuery({
    queryKey: ["catalog-latest", session.data?.viewer_key, id, platform],
    queryFn: () =>
      read("/api/v1/catalog/debug-entries", {
        query: {
          app_id: id,
          sort: "source_updated_at",
          page: 1,
          page_size: 1,
          ...(platform ? { platform } : {}),
        },
      }),
  });
  const featured = latest.data?.items[0];
  const remaining =
    entries.data?.items.filter((entry) => entry.id !== featured?.id) ?? [];
  if (app.error || entries.error || latest.error)
    return <ErrorBox error={app.error || entries.error || latest.error} />;
  return (
    <div className="catalog-download-page">
      <Link className="catalog-back" to="/">
        ← 全部应用
      </Link>
      <Title description={app.data?.description || "最新测试版与历史安装包"}>
        {app.data?.name ?? "应用安装包"}
      </Title>
      {latest.isPending ? (
        <Loading />
      ) : (
        featured && (
          <Panel className="catalog-featured" aria-label="最新安装包">
            <div className="catalog-featured-main">
              <div className="catalog-featured-info">
                <div className="catalog-featured-identity">
                  <AppIcon
                    name={featured.app.name}
                    value={featured.app.icon_data}
                  />
                  <div>
                    <span className="catalog-latest-badge">最新安装包</span>
                    <div className="catalog-featured-app">
                      {featured.app.name}
                      <span>
                        {featured.platform === "ios" ? "iOS" : "Android"} ·
                        Debug
                      </span>
                    </div>
                  </div>
                </div>
                <div className="catalog-featured-version">
                  <h2>{featuredVersion(featured)}</h2>
                  {featured.build_number && (
                    <span>Build {featured.build_number}</span>
                  )}
                </div>
              </div>
              <div className="catalog-featured-download">
                <DownloadControl key={featured.id} entry={featured} compact />
              </div>
            </div>
            <div className="catalog-featured-footer">
              <div className="catalog-featured-meta">
                <span>{size(featured.size_bytes)}</span>
                <span>
                  更新于{" "}
                  {date(featured.source_updated_at || featured.created_at)}
                </span>
              </div>
              <Link to={`/debug/${featured.id}`} title={featured.file_name}>
                版本详情
                <Icon name="arrow" size={14} />
              </Link>
            </div>
          </Panel>
        )
      )}
      <div className="catalog-history-heading">
        <h2>其他安装包</h2>
        <span className="muted">查找历史版本</span>
      </div>
      <div className="toolbar catalog-filters">
        {filters.search}
        <EntrySortPicker
          value={sort}
          onChange={(value) => {
            setSort(value);
            filters.setPage(1);
          }}
        />
        <label>
          <span id="platform-filter-label">平台</span>
          <Select
            aria-labelledby="platform-filter-label"
            style={{ minWidth: 160 }}
            value={platform}
            onChange={(value) => {
              setPlatform(String(value ?? ""));
              filters.setPage(1);
            }}
          >
            <Select.Option value="">全部</Select.Option>
            <Select.Option value="android">Android</Select.Option>
            <Select.Option value="ios">iOS</Select.Option>
          </Select>
        </label>
      </div>
      {entries.isPending || latest.isPending ? (
        <Loading />
      ) : (
        <>
          <List
            className="catalog-history-list"
            dataSource={remaining}
            emptyContent={
              <Empty>
                {featured
                  ? "当前筛选下没有其他安装包。"
                  : "没有符合条件的 Debug 包。"}
              </Empty>
            }
            renderItem={(entry) => (
              <List.Item key={entry.id}>
                <div className="catalog-history-content">
                  <div className="inline">
                    <Status value={entry.platform} />
                    <strong>{catalogVersion(entry)}</strong>
                    {entry.build_number && (
                      <span className="muted">Build {entry.build_number}</span>
                    )}
                  </div>
                  <Link
                    className="catalog-history-filename"
                    to={`/debug/${entry.id}`}
                  >
                    {entry.file_name}
                  </Link>
                  <p className="muted">
                    {size(entry.size_bytes)} ·{" "}
                    {date(entry.source_updated_at || entry.created_at)}
                  </p>
                </div>
                <Link
                  className="button catalog-history-action"
                  to={`/debug/${entry.id}`}
                >
                  查看并下载
                  <Icon name="chevron" size={16} />
                </Link>
              </List.Item>
            )}
          />
          <Pager data={entries.data} {...filters} />
        </>
      )}
    </div>
  );
}
function catalogVersion(entry: DTO<"CatalogEntry">) {
  return entry.version_label.replace(/^Tag[：:]\s*/i, "") || entry.file_name;
}
function featuredVersion(entry: DTO<"CatalogEntry">) {
  if (entry.version_name) return entry.version_name;
  const label = catalogVersion(entry);
  // Only simplify the conventional platform/channel tag; arbitrary release names remain intact.
  const version = label.match(
    /^(?:android|ios)-(?:debug|release)-v?(\d+\.\d+\.\d+(?:-[\w.-]+)?)(?:\+[\w.-]+)?$/i,
  );
  return version ? `v${version[1]}` : label;
}
export function CatalogEntryPage() {
  return (
    <DownloadGuard>
      <CatalogEntryContent />
    </DownloadGuard>
  );
}
function CatalogEntryContent() {
  const session = useSession();
  const { id = "" } = useParams();
  const q = useQuery({
    queryKey: ["catalog-entry", session.data?.viewer_key, id],
    queryFn: () => read("/api/v1/catalog/debug-entries/{id}", { id }),
  });
  if (q.isPending) return <Loading />;
  if (q.error || !q.data) return <ErrorBox error={q.error} />;
  const e = q.data;
  return (
    <>
      <Title>{e.app.name}</Title>
      <Link to={`/apps/${e.app.id}`}>← 所有版本</Link>
      <Panel className="panel download-detail">
        <div className="inline">
          <Status value={e.platform} />
          <Badge className="badge">Debug</Badge>
        </div>
        <h2>{e.file_name}</h2>
        <dl>
          <dt>{e.version_label_source === "tag" ? "来源 Tag" : "版本"}</dt>
          <dd>{e.version_label}</dd>
          <dt>构建号</dt>
          <dd>{e.build_number ?? "—"}</dd>
          <dt>文件大小</dt>
          <dd>{size(e.size_bytes)}</dd>
          <dt>发布时间</dt>
          <dd>{date(e.created_at)}</dd>
          <dt>缓存状态</dt>
          <dd>
            <Status value={e.cache.state} />
          </dd>
        </dl>
        {e.installation_notice && (
          <Notice className="notice">{e.installation_notice}</Notice>
        )}
        <DownloadControl key={e.id} entry={e} />
        <SharePage url={e.page_url} />
      </Panel>
    </>
  );
}
function DownloadControl({
  entry,
  compact = false,
}: {
  entry: DTO<"CatalogEntry">;
  compact?: boolean;
}) {
  const session = useSession();
  const cmd = useCommand();
  const [preparing, setPreparing] = useState(false);
  const [grant, setGrant] = useState<DTO<"DownloadGrant">>();
  const [expired, setExpired] = useState(false);
  const [started, setStarted] = useState(false);
  const prep = useQuery({
    queryKey: ["preparation", session.data?.viewer_key, entry.id],
    queryFn: () =>
      read("/api/v1/catalog/debug-entries/{id}/preparation", { id: entry.id }),
    enabled: preparing,
    refetchInterval: (query) =>
      query.state.error ||
      ["ready", "failed"].includes(query.state.data?.state ?? "")
        ? false
        : Math.max(1000, (query.state.data?.retry_after_seconds ?? 2) * 1000),
  });
  useEffect(() => {
    if (!grant) return;
    const timer = setTimeout(
      () => {
        setGrant(undefined);
        setExpired(true);
      },
      Math.max(0, new Date(grant.expires_at).getTime() - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [grant]);
  function requestGrant() {
    setExpired(false);
    setStarted(false);
    void cmd.run(
      `grant-${entry.id}`,
      (key) =>
        write(
          "/api/v1/catalog/debug-entries/{id}/download-grants",
          "post",
          undefined,
          { id: entry.id, key },
        ),
      (result) => {
        if ("download_url" in result) {
          setGrant(result);
          setPreparing(false);
        } else {
          setPreparing(true);
          void prep.refetch();
        }
      },
    );
  }
  return (
    <div className="download-control">
      {cmd.feedback}
      <ErrorBox error={prep.error} />
      {preparing && prep.data && (
        <div role="status">
          <div className="prose">
            缓存：
            <Status value={prep.data.state} />{" "}
            {size(prep.data.downloaded_bytes)} /{" "}
            {prep.data.total_bytes ? size(prep.data.total_bytes) : "大小待确认"}
          </div>
          {prep.data.state === "ready" ? (
            <p>文件已准备好，请再次获取临时下载链接。</p>
          ) : prep.data.state === "failed" ? (
            <Notice className="notice error">
              {prep.data.error_code}：{prep.data.error_message}
            </Notice>
          ) : (
            <Progress
              aria-label="缓存准备进度"
              percent={
                prep.data.total_bytes
                  ? Math.min(
                      100,
                      (prep.data.downloaded_bytes / prep.data.total_bytes) *
                        100,
                    )
                  : 0
              }
              showInfo={!!prep.data.total_bytes}
            />
          )}
        </div>
      )}
      {grant ? (
        <>
          <a
            className="button primary"
            href={grant.download_url}
            download={grant.file_name}
            referrerPolicy="no-referrer"
            onClick={() => setStarted(true)}
          >
            下载 {size(grant.size_bytes)}
          </a>
          {started && (
            <p role="status">已向浏览器发起下载，请查看浏览器的下载进度。</p>
          )}
          <p className="muted">
            链接截止 {date(grant.expires_at)}，有效期内持有链接即可使用。
          </p>
          <Disclosure title={<>文件校验值</>}>
            <p className="mono">SHA256: {grant.sha256}</p>
          </Disclosure>
        </>
      ) : (
        <Button
          className="primary"
          disabled={
            cmd.pending ||
            (preparing &&
              !prep.error &&
              !["ready", "failed"].includes(prep.data?.state ?? ""))
          }
          onClick={requestGrant}
        >
          {cmd.pending
            ? "正在授权…"
            : preparing && prep.data?.state === "ready"
              ? "获取临时下载链接"
              : expired
                ? "链接已过期，重新获取"
                : "获取下载链接"}
        </Button>
      )}
      <p className="muted">
        {compact
          ? "首次下载可能需要片刻准备"
          : "临时链接过期后需重新验证权限。首次访问可能需要等待缓存。"}
      </p>
    </div>
  );
}
