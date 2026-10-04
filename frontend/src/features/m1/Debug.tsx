import Select from "@douyinfe/semi-ui-19/lib/es/select";
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
import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { DownloadGuard } from "./Auth";
import { SharePage } from "../../shared/ui/SharePage";
import {
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
}: {
  value: EntrySort;
  onChange: (value: EntrySort) => void;
}) {
  const labelId = useId();
  return (
    <label>
      <span id={labelId}>排序</span>
      <Select
        aria-labelledby={labelId}
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
export function DebugListPage() {
  const { id = "" } = useParams();
  const filters = useFilters("搜索文件名、Tag 或版本…");
  const [sort, setSort] = useState<EntrySort>("source_updated_at");
  const q = useQuery({
    queryKey: ["debug-list", id, filters.page, filters.q, sort],
    queryFn: () =>
      read("/api/v1/apps/{id}/debug-entries", {
        id,
        query: { page: filters.page, q: filters.q, sort },
      }),
  });
  return (
    <>
      <Title>Debug 包管理</Title>
      <PageTabs className="tabs">
        <Link to={`/admin/apps/${id}`}>应用设置</Link>
        <Link to={`/admin/apps/${id}/releases`}>从 Release 导入</Link>
      </PageTabs>
      <div className="toolbar">
        {filters.search}
        <EntrySortPicker
          value={sort}
          onChange={(value) => {
            setSort(value);
            filters.setPage(1);
          }}
        />
      </div>
      <p className="muted">
        来源更新时间指 GitHub 附件更新时间；缺失时按导入时间排序。
      </p>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      <div className="card-grid">
        {q.data?.items.map((entry) => (
          <CardLink
            key={entry.id}
            className="panel app-card"
            to={`/admin/debug/${entry.id}`}
          >
            <h2>{entry.file_name}</h2>
            <p>{entry.version_name ?? `Tag ${entry.source_tag}`}</p>
            <div className="inline">
              <Status value={entry.platform} />
              <Status value={entry.cache.state} />
              <Badge className="badge">
                {entry.enabled ? "已启用" : "已停用"}
              </Badge>
            </div>
            <p>
              {size(entry.size_bytes)} · 导入：{date(entry.created_at)}
              <br />
              来源更新：{date(entry.source.asset_updated_at)}
            </p>
          </CardLink>
        ))}
      </div>
      {q.data && !q.data.items.length && (
        <Empty title={filters.q ? "没有匹配的 Debug 包" : "暂无 Debug 条目"}>
          {filters.q
            ? "请修改或清空搜索条件后重试。"
            : "请从 Release 选择安装包。"}
        </Empty>
      )}
      <Pager data={q.data} {...filters} />
    </>
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
        <p className="muted">分享固定分发页面；访问及下载仍需飞书身份验证。</p>
        <SharePage url={e.page_url} />
      </Panel>
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
  if (app.error || entries.error)
    return <ErrorBox error={app.error || entries.error} />;
  return (
    <>
      <Title description={app.data?.description}>
        {app.data?.name ?? "应用安装包"}
      </Title>
      <Link to="/">← 全部应用</Link>
      <div className="toolbar">
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
      <p className="muted">
        来源更新时间指 GitHub 附件更新时间；缺失时按导入时间排序。
      </p>
      {entries.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="card-grid">
            {entries.data?.items.map((e) => (
              <Panel className="panel" key={e.id}>
                <div className="inline">
                  <Status value={e.platform} />
                  <Badge className="badge">Debug</Badge>
                </div>
                <h2>
                  <Link to={`/debug/${e.id}`}>{e.file_name}</Link>
                </h2>
                <p>
                  {e.version_label_source === "tag" ? "Tag：" : "版本："}
                  {e.version_label}{" "}
                  {e.build_number && `· Build ${e.build_number}`}
                </p>
                <p className="muted">
                  {size(e.size_bytes)} · 导入：{date(e.created_at)}
                  <br />
                  来源更新：{date(e.source_updated_at)}
                </p>
                <DownloadControl entry={e} />
              </Panel>
            ))}
          </div>
          {!entries.data?.items.length && (
            <Empty>没有符合条件的 Debug 包。</Empty>
          )}
          <Pager data={entries.data} {...filters} />
        </>
      )}
    </>
  );
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
function DownloadControl({ entry }: { entry: DTO<"CatalogEntry"> }) {
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
        临时链接过期后需重新验证权限。首次访问可能需要等待缓存。
      </p>
    </div>
  );
}
