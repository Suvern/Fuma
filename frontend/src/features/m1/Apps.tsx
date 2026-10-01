import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";
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
  Title,
  text,
  useCommand,
  useFilters,
} from "../../shared/ui/common";

function Platforms({ selected = ["android"] }: { selected?: string[] }) {
  return (
    <fieldset>
      <legend>关联的端 *</legend>
      <Check
        label="Android"
        name="platforms"
        value="android"
        defaultChecked={selected.includes("android")}
      />
      <Check
        label="iOS"
        name="platforms"
        value="ios"
        defaultChecked={selected.includes("ios")}
      />
    </fieldset>
  );
}
export function AppsPage() {
  const filters = useFilters();
  const query = useQuery({
    queryKey: ["apps", filters.page, filters.q],
    queryFn: ({ signal }) =>
      read("/api/v1/apps", {
        signal,
        query: { page: filters.page, q: filters.q },
      }),
  });
  const cmd = useCommand();
  const navigate = useNavigate();
  return (
    <>
      <Title description="管理 App、关联平台和 GitHub 仓库。">应用管理</Title>
      <details className="panel">
        <summary>＋ 新建 App</summary>
        {cmd.feedback}
        <Form
          submit={(f) =>
            void cmd.run(
              JSON.stringify([...f]),
              (key) =>
                write(
                  "/api/v1/apps",
                  "post",
                  {
                    name: text(f, "name"),
                    public_slug: text(f, "public_slug"),
                    description: text(f, "description"),
                    platforms: f.getAll("platforms") as ("android" | "ios")[],
                  },
                  { key },
                ),
              (app) => navigate(`/admin/apps/${app.id}`),
            )
          }
        >
          <Field name="name" label="App 名称" required maxLength={100} />
          <Field
            name="public_slug"
            label="分发标识"
            required
            minLength={3}
            maxLength={64}
            pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
            help="小写字母、数字及连字符；创建后不可修改。"
          />
          <Field name="description" label="描述" maxLength={2000} />
          <Platforms />
          <button className="primary" disabled={cmd.pending}>
            创建 App
          </button>
        </Form>
      </details>
      {filters.search}
      <ErrorBox error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="card-grid">
            {query.data?.items.map((app) => (
              <Link
                className="app-card panel"
                key={app.id}
                to={`/admin/apps/${app.id}`}
              >
                <div className="app-monogram">{app.name[0]}</div>
                <h2>{app.name}</h2>
                <p>{app.description || "暂无描述"}</p>
                <div className="inline">
                  {app.platforms.map((p) => (
                    <Status key={p} value={p} />
                  ))}
                  <span className="badge">
                    {app.enabled ? "已启用" : "已停用"}
                  </span>
                </div>
                <p className="muted">
                  {app.debug_entry_count} 个 Debug 包 ·{" "}
                  {app.repository?.full_name ?? "未绑定仓库"}
                </p>
              </Link>
            ))}
          </div>
          {!query.data?.items.length && (
            <Empty>还没有 App，先创建应用以接入 GitHub Release。</Empty>
          )}
          <Pager data={query.data} {...filters} />
        </>
      )}
    </>
  );
}
export function AppPage() {
  const { id = "" } = useParams();
  const query = useQuery({
    queryKey: ["app", id],
    queryFn: () => read("/api/v1/apps/{id}", { id }),
  });
  if (query.isPending) return <Loading />;
  if (!query.data) return <ErrorBox error={query.error} />;
  return <AppEditor key={`${id}-${query.data.revision}`} app={query.data} />;
}
function AppEditor({ app }: { app: DTO<"App"> }) {
  const cmd = useCommand();
  const navigate = useNavigate();
  return (
    <>
      <Title description="维护基本信息，然后选择 Release 安装包或接入 GitHub Actions。">
        {app.name}
      </Title>
      <nav className="tabs">
        <Link to={`/admin/apps/${app.id}/releases`}>GitHub Releases</Link>
        <Link to={`/admin/apps/${app.id}/debug`}>Debug 包</Link>
        <Link to={`/admin/apps/${app.id}/actions`}>Actions 规则</Link>
        <Link to={`/admin/apps/${app.id}/events`}>构建事件</Link>
      </nav>
      {cmd.feedback}
      <div className="two-columns">
        <section className="panel">
          <h2>基本信息</h2>
          <Form
            submit={(f) =>
              void cmd.run("app-update", () =>
                write(
                  "/api/v1/apps/{id}",
                  "patch",
                  {
                    name: text(f, "name"),
                    description: text(f, "description"),
                    platforms: f.getAll("platforms") as ("android" | "ios")[],
                    enabled: f.has("enabled"),
                  },
                  { id: app.id, revision: app.revision },
                ),
              )
            }
          >
            <Field
              name="name"
              label="名称"
              defaultValue={app.name}
              required
              maxLength={100}
            />
            <Field
              name="public_slug"
              label="分发标识"
              value={app.public_slug}
              readOnly
            />
            <Field
              name="description"
              label="描述"
              defaultValue={app.description}
              maxLength={2000}
            />
            <Platforms selected={app.platforms} />
            <Check
              name="enabled"
              label="启用 App"
              defaultChecked={app.enabled}
            />
            <button disabled={cmd.pending} className="primary">
              保存
            </button>
          </Form>
          <button
            className="danger"
            disabled={cmd.pending}
            onClick={() => {
              if (
                window.confirm(
                  `删除 App「${app.name}」？历史记录将保留，下载入口将不可用。`,
                )
              )
                void cmd.run(
                  "app-delete",
                  () =>
                    write("/api/v1/apps/{id}", "delete", undefined, {
                      id: app.id,
                      revision: app.revision,
                    }),
                  () => navigate("/admin/apps"),
                );
            }}
          >
            删除 App
          </button>
        </section>
        <RepositoryBinding app={app} />
      </div>
    </>
  );
}
function RepositoryBinding({ app }: { app: DTO<"App"> }) {
  const filters = useFilters();
  const connectors = useQuery({
    queryKey: ["connectors-select", filters.page],
    queryFn: () =>
      read("/api/v1/connectors/github", { query: { page: filters.page } }),
  });
  const [connectorId, setConnectorId] = useState(
    app.repository?.connector_id ?? "",
  );
  const [repoName, setRepoName] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const repos = useQuery({
    queryKey: ["repositories", connectorId, q, page],
    queryFn: () =>
      read("/api/v1/connectors/github/{id}/repositories", {
        id: connectorId,
        query: { q, page },
      }),
    enabled: !!connectorId,
  });
  const cmd = useCommand();
  return (
    <section className="panel">
      <h2>绑定 GitHub 仓库</h2>
      <p>当前：{app.repository?.full_name ?? "未绑定"}</p>
      {cmd.feedback}
      <label className="field">
        Connector
        <select
          value={connectorId}
          onChange={(e) => {
            setConnectorId(e.target.value);
            setPage(1);
          }}
        >
          <option value="">选择 Connector</option>
          {connectors.data?.items.map((c) => (
            <option key={c.id} value={c.id} disabled={!c.enabled}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <Pager data={connectors.data} {...filters} />
      <ErrorBox error={connectors.error} />
      <form
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(text(new FormData(e.currentTarget), "repository_search"));
          setPage(1);
        }}
      >
        <Field
          name="repository_search"
          label="检索仓库"
          placeholder="owner/repository"
        />
        <button>检索</button>
      </form>
      <ErrorBox error={repos.error} />
      {repos.data?.items.map((repo) => (
        <button
          key={repo.id}
          className="list-option"
          onClick={() => setRepoName(repo.full_name)}
        >
          {repo.full_name} · {repo.private ? "私有" : "公开"}
        </button>
      ))}
      <Pager data={repos.data} page={page} setPage={setPage} />
      <Form
        submit={() =>
          void cmd.run("bind-repository", () =>
            write(
              "/api/v1/apps/{id}/repository",
              "put",
              { connector_id: connectorId, full_name: repoName },
              { id: app.id, revision: app.revision },
            ),
          )
        }
      >
        <Field
          label="仓库完整名称"
          name="full_name"
          value={repoName}
          onChange={(e) => setRepoName(e.target.value)}
          required
          pattern="[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
          help="也可填写已知仓库名称，保存时服务端核验权限与仓库身份。"
        />
        <button className="primary" disabled={cmd.pending || !connectorId}>
          验证并绑定
        </button>
      </Form>
      <Link to="/admin/connectors">管理 GitHub Connector</Link>
    </section>
  );
}
