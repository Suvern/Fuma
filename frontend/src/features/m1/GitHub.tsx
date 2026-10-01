import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import {
  Check,
  Checks,
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
} from "../../shared/ui/common";
export function ConnectorsPage() {
  const filters = useFilters();
  const q = useQuery({
    queryKey: ["connectors", filters.page, filters.q],
    queryFn: () =>
      read("/api/v1/connectors/github", {
        query: { page: filters.page, q: filters.q },
      }),
  });
  const cmd = useCommand();
  const [generation, setGeneration] = useState(0);
  return (
    <>
      <Title description="使用具有 Contents 读取权限的 PAT；Actions 自动分发另需 Actions 读取权限。">
        GitHub Connector
      </Title>
      <details className="panel">
        <summary>＋ 新建 Connector</summary>
        {cmd.feedback}
        <Form
          key={generation}
          submit={(f) =>
            void cmd.run(
              JSON.stringify(["connector-create", ...f]),
              (key) =>
                write(
                  "/api/v1/connectors/github",
                  "post",
                  {
                    name: text(f, "name"),
                    token: text(f, "token"),
                    enabled: true,
                  },
                  { key },
                ),
              () => setGeneration((x) => x + 1),
            )
          }
        >
          <Field label="名称" name="name" required maxLength={100} />
          <Field
            label="GitHub PAT"
            name="token"
            type="password"
            required
            minLength={16}
            autoComplete="off"
          />
          <button className="primary" disabled={cmd.pending}>
            保存 Connector
          </button>
        </Form>
      </details>
      {filters.search}
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.data?.items.map((c) => (
        <ConnectorEditor key={`${c.id}-${c.revision}`} connector={c} />
      ))}
      {q.data && !q.data.items.length && <Empty>尚未配置 Connector。</Empty>}
      <Pager data={q.data} {...filters} />
    </>
  );
}
function ConnectorEditor({ connector: c }: { connector: DTO<"Connector"> }) {
  const cmd = useCommand();
  const [result, setResult] = useState<DTO<"ConnectionTestResult">>();
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>{c.name}</h2>
        <Status value={c.last_test_status} />
      </div>
      <p className="muted">
        账号：{c.github_login ?? "未测试"} · 最近测试：{date(c.last_tested_at)}{" "}
        · {c.has_token ? "已保存凭据" : "缺少凭据"}
      </p>
      {cmd.feedback}
      <details>
        <summary>编辑配置</summary>
        <Form
          submit={(f) =>
            void cmd.run("connector-edit", () =>
              write(
                "/api/v1/connectors/github/{id}",
                "patch",
                {
                  name: text(f, "name"),
                  enabled: f.has("enabled"),
                  ...(text(f, "token") ? { token: text(f, "token") } : {}),
                },
                { id: c.id, revision: c.revision },
              ),
            )
          }
        >
          <Field
            label="名称"
            name="name"
            defaultValue={c.name}
            required
            maxLength={100}
          />
          <Field
            label="替换 PAT"
            name="token"
            type="password"
            minLength={16}
            autoComplete="off"
            help="留空保留现有凭据。"
          />
          <Check label="启用" name="enabled" defaultChecked={c.enabled} />
          <button disabled={cmd.pending}>保存修改</button>
        </Form>
      </details>
      <Form
        className="inline-form"
        submit={(f) =>
          void cmd.run(
            "connector-test",
            () =>
              write(
                "/api/v1/connectors/github/{id}/test",
                "post",
                {
                  check_actions: f.has("check_actions"),
                  ...(text(f, "repository_full_name")
                    ? { repository_full_name: text(f, "repository_full_name") }
                    : {}),
                },
                { id: c.id },
              ),
            setResult,
          )
        }
      >
        <Field
          name="repository_full_name"
          label="测试仓库（可选）"
          placeholder="owner/repository"
        />
        <Check label="检查 Actions 权限" name="check_actions" />
        <button disabled={cmd.pending}>测试连接</button>
      </Form>
      {result && <Checks checks={result.checks} />}
      <button
        className="danger"
        disabled={cmd.pending}
        onClick={() => {
          if (window.confirm(`删除 Connector「${c.name}」？`))
            void cmd.run("connector-delete", () =>
              write("/api/v1/connectors/github/{id}", "delete", undefined, {
                id: c.id,
                revision: c.revision,
              }),
            );
        }}
      >
        删除 Connector
      </button>
    </section>
  );
}
export function ReleasesPage() {
  const { id = "" } = useParams();
  const filters = useFilters();
  const [prerelease, setPrerelease] = useState("all");
  const [assetName, setAssetName] = useState("");
  const [task, setTask] = useState<DTO<"TaskAccepted">>();
  const q = useQuery({
    queryKey: ["releases", id, filters.page, filters.q, prerelease, assetName],
    queryFn: () =>
      read("/api/v1/apps/{id}/github/releases", {
        id,
        query: {
          page: filters.page,
          q: filters.q,
          prerelease,
          asset_name: assetName,
        },
      }),
    refetchInterval: (query) =>
      query.state.data?.sync_state === "syncing" ? 2500 : false,
  });
  const cmd = useCommand();
  return (
    <>
      <Title description="检索仓库的 Release，选择 APK 或 IPA 作为 Debug 分发条目。">
        Release 安装包
      </Title>
      <Link to={`/admin/apps/${id}`}>← 应用设置</Link>
      <div className="toolbar">
        {filters.search}
        <label>
          预发布
          <select
            value={prerelease}
            onChange={(e) => {
              setPrerelease(e.target.value);
              filters.setPage(1);
            }}
          >
            <option value="all">全部</option>
            <option value="only">仅预发布</option>
            <option value="exclude">排除预发布</option>
          </select>
        </label>
        <label>
          文件名筛选
          <input
            value={assetName}
            onChange={(e) => {
              setAssetName(e.target.value);
              filters.setPage(1);
            }}
          />
        </label>
        <button
          disabled={cmd.pending}
          onClick={() =>
            void cmd.run(
              "release-sync",
              (key) =>
                write(
                  "/api/v1/apps/{id}/github/releases/refresh",
                  "post",
                  undefined,
                  { id, key },
                ),
              setTask,
            )
          }
        >
          同步 Releases
        </button>
      </div>
      {cmd.feedback}
      <TaskNotice task={task} />
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.data && (
        <p className="muted">
          同步状态：
          <Status value={q.data.sync_state} /> · {date(q.data.synced_at)}{" "}
          {q.data.sync_error_code}
        </p>
      )}
      {q.data?.items.map((release) => (
        <ReleaseCard key={release.id} appId={id} release={release} />
      ))}
      {q.data && !q.data.items.length && (
        <Empty>未找到 Release，请检查搜索条件或发起同步。</Empty>
      )}
      <Pager data={q.data} {...filters} />
    </>
  );
}
function ReleaseCard({
  appId,
  release: r,
}: {
  appId: string;
  release: DTO<"GitHubRelease">;
}) {
  const cmd = useCommand();
  const [selected, setSelected] = useState<string[]>([]);
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>{r.name || r.tag_name}</h2>
        <div className="inline">
          <span className="badge">Tag {r.tag_name}</span>
          {r.draft && <span className="badge">草稿 · 不可分发</span>}
          {r.prerelease && <span className="badge">预发布</span>}
        </div>
      </div>
      <p className="muted">{date(r.published_at)}</p>
      <details>
        <summary>发布说明</summary>
        <p className="release-notes">{r.body || "暂无说明"}</p>
      </details>
      {cmd.feedback}
      <Form
        submit={(f) =>
          void cmd.run(
            JSON.stringify([r.id, selected, ...f]),
            (key) =>
              write(
                "/api/v1/apps/{id}/debug-entries",
                "post",
                {
                  release_id: r.id,
                  enabled: true,
                  assets: selected.map((asset_id) => ({
                    asset_id,
                    platform: r.assets.find((a) => a.id === asset_id)!
                      .platform!,
                    version_name: text(f, "version_name") || null,
                    build_number: text(f, "build_number") || null,
                  })),
                },
                { id: appId, key },
              ),
            () => setSelected([]),
          )
        }
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>选择安装包</th>
                <th>平台</th>
                <th>大小</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {r.assets.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Check
                      label={a.name}
                      name="asset"
                      checked={selected.includes(a.id)}
                      disabled={
                        r.draft ||
                        !a.supported ||
                        !a.platform ||
                        !!a.debug_entry_id
                      }
                      onChange={(e) =>
                        setSelected((s) =>
                          e.target.checked
                            ? [...s, a.id]
                            : s.filter((x) => x !== a.id),
                        )
                      }
                    />
                  </td>
                  <td>
                    {a.platform ? <Status value={a.platform} /> : "不支持"}
                  </td>
                  <td>{size(a.size_bytes)}</td>
                  <td>
                    {a.debug_entry_id ? (
                      <Link to={`/admin/debug/${a.debug_entry_id}`}>
                        已导入
                      </Link>
                    ) : (
                      <Status value={a.cache_state} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="inline-form">
          <Field
            name="version_name"
            label="版本号（可选）"
            maxLength={100}
            help="未填写时仅显示来源 Tag。"
          />
          <Field name="build_number" label="构建号（可选）" maxLength={100} />
        </div>
        <button className="primary" disabled={cmd.pending || !selected.length}>
          导入 {selected.length || ""} 个 Debug 包
        </button>
      </Form>
    </section>
  );
}
