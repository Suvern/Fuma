import { useEffect, useState } from "react";
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
export function DebugListPage() {
  const { id = "" } = useParams();
  const filters = useFilters();
  const q = useQuery({
    queryKey: ["debug-list", id, filters.page, filters.q],
    queryFn: () =>
      read("/api/v1/apps/{id}/debug-entries", {
        id,
        query: { page: filters.page, q: filters.q },
      }),
  });
  return (
    <>
      <Title>Debug 包管理</Title>
      <nav className="tabs">
        <Link to={`/admin/apps/${id}`}>应用设置</Link>
        <Link to={`/admin/apps/${id}/releases`}>从 Release 导入</Link>
      </nav>
      {filters.search}
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      <div className="card-grid">
        {q.data?.items.map((entry) => (
          <Link
            key={entry.id}
            className="panel app-card"
            to={`/admin/debug/${entry.id}`}
          >
            <h2>{entry.file_name}</h2>
            <p>{entry.version_name ?? `Tag ${entry.source_tag}`}</p>
            <div className="inline">
              <Status value={entry.platform} />
              <Status value={entry.cache.state} />
              <span className="badge">
                {entry.enabled ? "已启用" : "已停用"}
              </span>
            </div>
            <p>
              {size(entry.size_bytes)} · {date(entry.created_at)}
            </p>
          </Link>
        ))}
      </div>
      {q.data && !q.data.items.length && (
        <Empty>暂无 Debug 条目，请从 Release 选择安装包。</Empty>
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
      <section className="panel">
        <div className="inline">
          <Status value={e.platform} />
          <Status value={e.cache.state} />
          <span className="badge">Debug</span>
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
          <p className="notice error">
            {e.cache.error_code}：{e.cache.error_message}
          </p>
        )}
        <div className="toolbar">
          <button
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
          </button>
          <button
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
          </button>
          <Link className="button" to={`/debug/${id}`}>
            查看分发页面
          </Link>
        </div>
        <p className="muted">分享固定分发页面；访问及下载仍需飞书身份验证。</p>
        <SharePage url={e.page_url} />
      </section>
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
  const filters = useFilters();
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
              <Link
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
              </Link>
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
  const filters = useFilters();
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
    ],
    queryFn: () =>
      read("/api/v1/catalog/debug-entries", {
        query: {
          app_id: id,
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
        <label>
          平台
          <select
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value);
              filters.setPage(1);
            }}
          >
            <option value="">全部</option>
            <option value="android">Android</option>
            <option value="ios">iOS</option>
          </select>
        </label>
      </div>
      {entries.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="card-grid">
            {entries.data?.items.map((e) => (
              <section className="panel" key={e.id}>
                <div className="inline">
                  <Status value={e.platform} />
                  <span className="badge">Debug</span>
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
                  {size(e.size_bytes)} · {date(e.created_at)}
                </p>
                <DownloadControl entry={e} />
              </section>
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
      <section className="panel download-detail">
        <div className="inline">
          <Status value={e.platform} />
          <span className="badge">Debug</span>
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
          <p className="notice">{e.installation_notice}</p>
        )}
        <DownloadControl key={e.id} entry={e} />
        <SharePage url={e.page_url} />
      </section>
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
          <p>
            缓存：
            <Status value={prep.data.state} />{" "}
            {size(prep.data.downloaded_bytes)} /{" "}
            {prep.data.total_bytes ? size(prep.data.total_bytes) : "大小待确认"}
          </p>
          {prep.data.state === "ready" ? (
            <p>文件已准备好，请再次获取临时下载链接。</p>
          ) : prep.data.state === "failed" ? (
            <p className="notice error">
              {prep.data.error_code}：{prep.data.error_message}
            </p>
          ) : (
            <progress
              max={prep.data.total_bytes ?? undefined}
              value={
                prep.data.total_bytes ? prep.data.downloaded_bytes : undefined
              }
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
          <details>
            <summary>文件校验值</summary>
            <p className="mono">SHA256: {grant.sha256}</p>
          </details>
        </>
      ) : (
        <button
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
        </button>
      )}
      <p className="muted">
        临时链接过期后需重新验证权限。首次访问可能需要等待缓存。
      </p>
    </div>
  );
}
