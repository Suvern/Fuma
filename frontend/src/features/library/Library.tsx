import { Select, DateInput, TextArea } from "../../shared/ui/FormControls";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { StorageChoice } from "./Storage";
import { DefaultReleaseControl, PackageManagement } from "./Management";
import { Button, Panel, PageTabs, Notice } from "../../shared/ui/controls";
import {
  Empty,
  ErrorBox,
  Field,
  Form,
  Loading,
  Pager,
  Title,
  date,
  text,
  useCommand,
  useFilters,
  useSession,
} from "../../shared/ui/common";

const states: Record<string, string> = {
  receiving: "等待续传",
  processing: "解析入库中",
  ready: "已入库",
  failed: "处理失败",
  cancelled: "已取消",
  expired: "已过期",
  draft: "草稿",
  published: "已发布",
  unpublished: "已下架",
  archived: "已归档",
};

export function PackagesPage() {
  const { id = "" } = useParams();
  const filters = useFilters("搜索文件名、包标识或版本…");
  const [uploadPage, setUploadPage] = useState(1);
  const [platformFilter, setPlatformFilter] = useState("");
  const [modeFilter, setModeFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdBefore, setCreatedBefore] = useState("");
  const invalidRange =
    !!createdFrom && !!createdBefore && createdFrom >= createdBefore;
  const queryClient = useQueryClient();
  const packages = useQuery({
    queryKey: [
      "library-packages",
      id,
      filters.page,
      filters.q,
      platformFilter,
      modeFilter,
      stateFilter,
      sourceFilter,
      createdFrom,
      createdBefore,
    ],
    enabled: !invalidRange,
    refetchOnMount: "always",
    queryFn: () =>
      read("/api/v1/apps/{id}/packages", {
        id,
        query: {
          page: filters.page,
          q: filters.q,
          platform: platformFilter || undefined,
          mode: modeFilter || undefined,
          state: stateFilter || undefined,
          source_kind: sourceFilter || undefined,
          created_from: createdFrom
            ? new Date(createdFrom).toISOString()
            : undefined,
          created_before: createdBefore
            ? new Date(createdBefore).toISOString()
            : undefined,
        },
      }),
  });
  const uploads = useQuery({
    queryKey: ["library-uploads", id, uploadPage],
    queryFn: () =>
      read("/api/v1/apps/{id}/uploads", { id, query: { page: uploadPage } }),
    refetchInterval: 5000,
  });
  const uploadStates = uploads.data?.items
    .map((u) => `${u.id}:${u.state}`)
    .join("|");
  useEffect(() => {
    if (uploadStates !== undefined)
      void queryClient.invalidateQueries({
        queryKey: ["library-packages", id],
      });
  }, [id, uploadStates, queryClient]);
  return (
    <div className="app-tab-page packages-page">
      <Title description="手工上传 APK / IPA，解析并校验包标识后入库。入库不会自动发布。">
        安装包
      </Title>
      <PageTabs />
      <Uploader
        appId={id}
        uploads={uploads.data?.items ?? []}
        loading={uploads.isPending}
        failed={uploads.isError}
      />
      <Pager data={uploads.data} page={uploadPage} setPage={setUploadPage} />
      <ErrorBox error={uploads.error} />
      {uploads.isError && (
        <Button
          type="button"
          disabled={uploads.isFetching}
          onClick={() => void uploads.refetch()}
        >
          重试加载上传记录
        </Button>
      )}
      <section
        className="app-tab-filters package-filter-panel"
        aria-label="安装包筛选"
      >
        {filters.search}
        <div className="toolbar package-filters">
          <div className="field">
            <Select
              label="平台"
              value={platformFilter}
              onChange={(e) => {
                setPlatformFilter(e.target.value);
                filters.setPage(1);
              }}
            >
              <option value="">全部平台</option>
              <option value="android">Android</option>
              <option value="ios">iOS</option>
            </Select>
          </div>
          <div className="field">
            <Select
              label="模式"
              value={modeFilter}
              onChange={(e) => {
                setModeFilter(e.target.value);
                filters.setPage(1);
              }}
            >
              <option value="">全部模式</option>
              <option value="debug">Debug</option>
              <option value="release">Release</option>
            </Select>
          </div>
          <div className="field">
            <Select
              label="状态"
              value={stateFilter}
              onChange={(e) => {
                setStateFilter(e.target.value);
                filters.setPage(1);
              }}
            >
              <option value="">全部状态</option>
              <option value="processing">处理中</option>
              <option value="ready">已入库</option>
              <option value="deleting">清理中</option>
              <option value="deleted">已删除</option>
            </Select>
          </div>
          <div className="field">
            <Select
              label="来源"
              value={sourceFilter}
              onChange={(e) => {
                setSourceFilter(e.target.value);
                filters.setPage(1);
              }}
            >
              <option value="">全部来源</option>
              <option value="upload">手工上传</option>
              <option value="github">GitHub</option>
            </Select>
          </div>
          <div className="field date-filter">
            <DateInput
              label="入库起始时间（本地时间，含）"
              type="datetime-local"
              value={createdFrom}
              onChange={(e) => {
                setCreatedFrom(e.target.value);
                filters.setPage(1);
              }}
            />
          </div>
          <div className="field date-filter">
            <DateInput
              label="入库结束时间（本地时间，不含）"
              type="datetime-local"
              value={createdBefore}
              min={createdFrom || undefined}
              onChange={(e) => {
                setCreatedBefore(e.target.value);
                filters.setPage(1);
              }}
            />
          </div>
          <Button
            type="button"
            onClick={() => {
              setPlatformFilter("");
              setModeFilter("");
              setStateFilter("");
              setSourceFilter("");
              setCreatedFrom("");
              setCreatedBefore("");
              filters.reset();
            }}
          >
            清空筛选
          </Button>
        </div>
      </section>
      {invalidRange && <p role="alert">入库起始时间必须早于结束时间。</p>}
      <ErrorBox error={packages.error} />
      {packages.isError && (
        <Button
          type="button"
          disabled={packages.isFetching || invalidRange}
          onClick={() => void packages.refetch()}
        >
          重试加载安装包
        </Button>
      )}
      {packages.isPending && !invalidRange && <Loading />}
      {packages.data && !packages.data.items.length && (
        <Empty>
          {filters.q ||
          platformFilter ||
          modeFilter ||
          stateFilter ||
          sourceFilter ||
          createdFrom ||
          createdBefore
            ? "没有匹配的安装包，请调整条件或清空筛选。"
            : "暂无已入库安装包。点击上传安装包开始，完成后请等待解析任务。"}
        </Empty>
      )}
      <div className="card-grid">
        {packages.data?.items.map((p) => (
          <Panel key={p.id}>
            <h2>{p.file_name}</h2>
            <p>
              {p.platform} · {p.mode} · {p.version_name} ({p.build_number})
            </p>
            <p>
              <code>{p.package_identifier}</code>
            </p>
            <p>
              {(p.size_bytes / 1024 / 1024).toFixed(2)} MiB ·{" "}
              {date(p.created_at)}
            </p>
            <p>{p.signature_status}</p>
            <p>
              状态：{states[p.state] || p.state} · 来源：
              {p.source_kind === "github" ? "GitHub" : "手工上传"}
            </p>
            <details>
              <summary>完整校验信息</summary>
              <p>
                SHA-256：<code>{p.sha256}</code>
              </p>
              <p>最低系统版本：{p.min_os ?? "未知"}</p>
              <p>架构：{p.architectures.join(", ") || "未提供"}</p>
              <p>签名摘要：{p.signer_fingerprints.join(", ") || "未验证"}</p>
              <p>解析器：{p.parser_version}</p>
            </details>
            <PackageReferences id={p.id} />
            <PackageManagement package={p} />
          </Panel>
        ))}
      </div>
      <Pager data={packages.data} {...filters} />
    </div>
  );
}

function PackageReferences({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["package-detail", id],
    queryFn: () => read("/api/v1/packages/{id}", { id }),
    enabled: open,
    staleTime: 0,
  });
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>来源、上传任务与发布引用</summary>
      {open && (
        <>
          <ErrorBox error={detail.error} />
          {detail.isPending && <Loading />}
          {detail.data && (
            <>
              <h3>来源快照</h3>
              {detail.data.source_snapshot ? (
                <pre
                  style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
                >
                  {JSON.stringify(detail.data.source_snapshot, null, 2)}
                </pre>
              ) : (
                <p>手工上传，无外部来源快照。</p>
              )}
              <h3>关联上传</h3>
              {!detail.data.related_uploads?.length && (
                <p>暂无关联上传记录。</p>
              )}
              {detail.data.related_uploads?.map((upload) => (
                <p key={upload.id}>
                  {upload.file_name} · {date(upload.created_at)} ·{" "}
                  {states[upload.state] || upload.state}{" "}
                  {upload.task_id && (
                    <Link to={`/admin/tasks/${upload.task_id}`}>查看任务</Link>
                  )}
                </p>
              ))}
              <h3>发布引用</h3>
              {!detail.data.publication_refs?.length && (
                <p>尚未加入任何发布。</p>
              )}
              {detail.data.publication_refs?.map((publication) => (
                <p key={publication.id}>
                  <Link to={`/admin/versions/${publication.version_id}`}>
                    查看版本发布
                  </Link>{" "}
                  {publication.platform} · {publication.mode} ·{" "}
                  {states[publication.state] || publication.state} · 修订{" "}
                  {publication.revision}
                </p>
              ))}
            </>
          )}
        </>
      )}
    </details>
  );
}

function Uploader({
  appId,
  uploads,
  loading,
  failed,
}: {
  appId: string;
  uploads: DTO<"UploadSession">[];
  loading: boolean;
  failed: boolean;
}) {
  const [file, setFile] = useState<File>();
  const fileInput = useRef<HTMLInputElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [platform, setPlatform] = useState<"android" | "ios">("android");
  const [mode, setMode] = useState<"debug" | "release">("debug");
  const [storage, setStorage] = useState("default");
  const [resume, setResume] = useState<DTO<"UploadSession">>();
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const abort = useRef<AbortController | null>(null);
  const intent = useRef<{
    file: File;
    platform: string;
    mode: string;
    storage: string;
    key: string;
  } | null>(null);
  const queryClient = useQueryClient();
  const cmd = useCommand();
  useEffect(() => () => abort.current?.abort(), []);
  async function upload() {
    if (!file || abort.current) return;
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setFailure("");
    setMessage("");
    setProgress(0);
    try {
      if (file.size > 4 * 1024 ** 3 || !file.size)
        throw new Error("文件必须大于 0 且不超过 4 GiB。");
      if (
        !intent.current ||
        intent.current.file !== file ||
        intent.current.platform !== platform ||
        intent.current.mode !== mode ||
        intent.current.storage !== storage
      )
        intent.current = {
          file,
          platform,
          mode,
          storage,
          key: crypto.randomUUID(),
        };
      let session = resume
        ? await read("/api/v1/uploads/{id}", { id: resume.id })
        : await write(
            "/api/v1/apps/{id}/uploads",
            "post",
            {
              file_name: file.name,
              declared_size: file.size,
              platform,
              mode,
              ...(storage !== "default"
                ? { storage_location_id: storage || null }
                : {}),
            },
            { id: appId, key: intent.current.key },
          );
      setResume(session);
      if (
        session.file_name !== file.name ||
        session.declared_size !== file.size
      )
        throw new Error("请选择原来的同名同大小文件；内容不同请创建新上传。");
      if (session.state !== "receiving")
        throw new Error("此会话已提交或不可续传，请刷新状态。");
      const context = await read("/api/v1/auth/browser-context");
      for (let number = 1; number <= session.expected_parts; number++) {
        controller.signal.throwIfAborted();
        const start = (number - 1) * session.chunk_size;
        const bytes = await file
          .slice(start, Math.min(start + session.chunk_size, file.size))
          .arrayBuffer();
        const digest = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        )
          .map((b) => b.toString(16).padStart(2, "0"))
          .join("");
        const done = session.parts.find((p) => p.part_number === number);
        if (done && done.sha256 !== digest)
          throw new Error(
            "已上传分片与所选文件内容不同，请取消该会话并重新上传。",
          );
        if (!done) {
          const response = await fetch(
            `/api/v1/uploads/${session.id}/parts/${number}`,
            {
              method: "PUT",
              headers: {
                "Content-Type": "application/octet-stream",
                "X-CSRF-Token": context.csrf_token,
                "X-Chunk-SHA256": digest,
              },
              body: bytes,
              signal: AbortSignal.any([
                controller.signal,
                AbortSignal.timeout(120000),
              ]),
            },
          );
          if (!response.ok) {
            const error = await response.json().catch(() => null);
            throw new Error(
              error?.error?.message ?? `分片上传失败（${response.status}）`,
            );
          }
        }
        setProgress(
          Math.round(
            (Math.min(start + bytes.byteLength, file.size) / file.size) * 100,
          ),
        );
      }
      controller.signal.throwIfAborted();
      session = await write(
        "/api/v1/uploads/{id}/complete",
        "post",
        undefined,
        { id: session.id },
      );
      setResume(undefined);
      intent.current = null;
      setFile(undefined);
      setMessage("上传已提交，隔离解析器正在处理。关闭页面不影响服务端任务。");
      void queryClient.invalidateQueries();
    } catch (error) {
      setFailure(
        controller.signal.aborted
          ? "已暂停；重新选择原文件后可续传。"
          : error instanceof Error
            ? error.message
            : "上传失败，请重试。",
      );
    } finally {
      abort.current = null;
      setBusy(false);
      void queryClient.invalidateQueries({
        queryKey: ["library-uploads", appId],
      });
    }
  }
  return (
    <Panel>
      <div className="section-heading">
        <h2>上传与处理记录</h2>
        <Button
          type="button"
          className={expanded ? "" : "primary"}
          disabled={busy}
          aria-expanded={expanded}
          aria-controls="package-upload-form"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "收起上传表单" : "上传安装包"}
        </Button>
      </div>
      {expanded && (
        <div id="package-upload-form">
          <p>
            单文件最多 4 GiB，16 MiB
            分片。刷新后重新选择原文件可续传；必须先在应用设置配置对应平台和模式的包标识。
          </p>
          <fieldset
            disabled={busy}
            style={{ border: 0, padding: 0, minWidth: 0 }}
          >
            <div className="field">
              <Select
                label="平台"
                value={platform}
                onChange={(e) =>
                  setPlatform(e.target.value as "android" | "ios")
                }
                disabled={!!resume}
              >
                <option value="android">Android APK</option>
                <option value="ios">iOS IPA</option>
              </Select>
            </div>
            <div className="field">
              <Select
                label="模式"
                value={mode}
                onChange={(e) => setMode(e.target.value as "debug" | "release")}
                disabled={!!resume}
              >
                <option value="debug">Debug</option>
                <option value="release">Release</option>
              </Select>
            </div>
            <label>
              选择安装包
              <input
                ref={fileInput}
                className="form-control-proxy"
                aria-label="选择安装包"
                type="file"
                accept={platform === "android" ? ".apk" : ".ipa"}
                onChange={(e) => setFile(e.target.files?.[0])}
              />
              <Button type="button" onClick={() => fileInput.current?.click()}>
                选择 {platform === "android" ? "APK" : "IPA"} 文件
              </Button>
              <span>{file?.name ?? "尚未选择文件"}</span>
            </label>
            <StorageChoice
              appId={appId}
              mode="private"
              value={storage}
              onChange={setStorage}
              disabled={!!resume}
            />
          </fieldset>
          {resume && (
            <p>
              续传会话：{resume.file_name} · {resume.id}
            </p>
          )}
          {failure && <p role="alert">{failure}</p>}
          {message && <Notice>{message}</Notice>}
          {busy && (
            <>
              <progress max={100} value={progress} aria-label="上传进度" />
              <p>{progress}%</p>
            </>
          )}
          <div className="toolbar">
            <Button
              type="button"
              className="primary"
              disabled={busy || !file}
              onClick={() => void upload()}
            >
              {resume ? "继续上传" : "开始上传"}
            </Button>
            {busy && (
              <Button type="button" onClick={() => abort.current?.abort()}>
                暂停上传
              </Button>
            )}
            {resume && !busy && (
              <Button
                type="button"
                onClick={() => {
                  setResume(undefined);
                  setFile(undefined);
                }}
              >
                新建上传
              </Button>
            )}
          </div>
        </div>
      )}
      {cmd.feedback}
      <h3>最近上传</h3>
      {loading && <Loading />}
      {!loading && !failed && !uploads.length && (
        <p className="muted">暂无上传记录。</p>
      )}
      {uploads.map((u) => (
        <div key={u.id} className="panel">
          <p>
            {u.file_name} · {states[u.state]} · 已收到 {u.parts.length}/
            {u.expected_parts} 片
          </p>
          {u.error_message && <p role="alert">{u.error_message}</p>}
          {u.task_id && (
            <Link to={`/admin/tasks/${u.task_id}`}>查看解析任务</Link>
          )}
          {u.state === "receiving" && (
            <Button
              type="button"
              disabled={busy}
              onClick={() => {
                setExpanded(true);
                setResume(u);
                setPlatform(u.platform);
                setMode(u.mode);
                setStorage(u.storage_location_id || "");
                setFile(undefined);
                setMessage("请重新选择原文件，续传时会逐片核对内容。");
              }}
            >
              选择此会话续传
            </Button>
          )}
          {u.state === "failed" && (
            <Button
              type="button"
              disabled={cmd.pending}
              onClick={() =>
                void cmd.run(`retry-${u.id}`, () =>
                  write("/api/v1/uploads/{id}/retry", "post", undefined, {
                    id: u.id,
                  }),
                )
              }
            >
              重试解析
            </Button>
          )}
          {["receiving", "failed", "expired"].includes(u.state) && (
            <Button
              type="button"
              disabled={busy || cmd.pending}
              onClick={() =>
                void cmd.run(
                  `cancel-${u.id}`,
                  () =>
                    write("/api/v1/uploads/{id}", "delete", undefined, {
                      id: u.id,
                    }),
                  () => {
                    if (resume?.id === u.id) setResume(undefined);
                  },
                  "上传已取消。",
                  "取消此上传并清理暂存分片？",
                )
              }
            >
              取消上传
            </Button>
          )}
        </div>
      ))}
    </Panel>
  );
}

export function VersionsPage() {
  const { id = "" } = useParams();
  const cmd = useCommand();
  const [creating, setCreating] = useState(false);
  const filters = useFilters("搜索版本名称…");
  const versions = useQuery({
    queryKey: ["versions", id, filters.page, filters.q],
    queryFn: () =>
      read("/api/v1/apps/{id}/versions", {
        id,
        query: { page: filters.page, q: filters.q },
      }),
  });
  return (
    <div className="app-tab-page versions-page">
      <Title description="版本可包含 Android 与 iOS 的独立发布修订。上传入库后，需要在这里显式发布。">
        版本发布
      </Title>
      <PageTabs />
      {cmd.feedback}
      <div className="app-tab-filters versions-toolbar">
        {filters.search}
        <Button
          type="button"
          className="primary"
          aria-expanded={creating}
          aria-controls="version-create-form"
          onClick={() => setCreating(!creating)}
          disabled={cmd.pending}
        >
          {creating ? "取消新建版本" : "新建版本"}
        </Button>
      </div>
      {creating && (
        <Panel id="version-create-form">
          <h2>新建版本</h2>
          <Form
            submit={(f) =>
              void cmd.run(
                `create-version-${id}-${JSON.stringify(Object.fromEntries(f))}`,
                (key) =>
                  write(
                    "/api/v1/apps/{id}/versions",
                    "post",
                    {
                      display_name: text(f, "display_name"),
                      mode: text(f, "mode") as "debug" | "release",
                      release_notes: text(f, "release_notes"),
                    },
                    { id, key },
                  ),
                () => setCreating(false),
                "版本草稿已创建，请在列表中打开并选择安装包发布。",
              )
            }
          >
            <Field
              name="display_name"
              label="版本名称"
              required
              maxLength={100}
            />
            <div className="field">
              <Select label="模式" name="mode">
                <option value="debug">Debug</option>
                <option value="release">Release</option>
              </Select>
            </div>
            <label>
              发布说明
              <TextArea name="release_notes" maxLength={10000} />
            </label>
            <Button className="primary" disabled={cmd.pending}>
              创建版本草稿
            </Button>
          </Form>
        </Panel>
      )}
      <ErrorBox error={versions.error} />
      {versions.isError && (
        <Button
          type="button"
          disabled={versions.isFetching}
          onClick={() => void versions.refetch()}
        >
          重试加载版本
        </Button>
      )}
      {versions.isPending && <Loading />}
      {versions.data && !versions.data.items.length && (
        <Empty>
          {filters.q
            ? "没有匹配的版本，请调整搜索条件。"
            : "暂无版本，点击新建版本组织已入库安装包。"}
        </Empty>
      )}
      {versions.data?.items.map((v) => (
        <Panel key={v.id}>
          <h2>
            <Link to={`/admin/versions/${v.id}`}>{v.display_name}</Link>
          </h2>
          <p>
            {v.mode} · {date(v.created_at)}
          </p>
          <p className="version-notes-preview">
            {v.release_notes || "暂无发布说明"}
          </p>
        </Panel>
      ))}
      <Pager data={versions.data} {...filters} />
    </div>
  );
}

export function VersionPage() {
  const { id = "" } = useParams();
  const version = useQuery({
    queryKey: ["version", id],
    queryFn: () => read("/api/v1/versions/{id}", { id }),
  });
  if (version.isPending) return <Loading />;
  if (!version.data) return <ErrorBox error={version.error} />;
  return <VersionEditor version={version.data} />;
}
function VersionEditor({ version: v }: { version: DTO<"VersionInfo"> }) {
  const cmd = useCommand();
  const [selected, setSelected] = useState<string[]>([]);
  const [platform, setPlatform] = useState<"android" | "ios">("android");
  const [publicStorage, setPublicStorage] = useState("");
  const [publicationPage, setPublicationPage] = useState(1);
  const filters = useFilters("搜索文件名、包标识或版本…");
  const packages = useQuery({
    queryKey: [
      "version-packages",
      v.app_id,
      filters.page,
      filters.q,
      platform,
      v.mode,
    ],
    queryFn: () =>
      read("/api/v1/apps/{id}/packages", {
        id: v.app_id,
        query: {
          page: filters.page,
          q: filters.q,
          platform,
          mode: v.mode,
          state: "ready",
        },
      }),
  });
  const publications = useQuery({
    queryKey: ["publications", v.id, publicationPage],
    queryFn: () =>
      read("/api/v1/versions/{id}/publications", {
        id: v.id,
        query: { page: publicationPage },
      }),
    refetchInterval: 5000,
  });
  return (
    <>
      <Title>{v.display_name}</Title>
      <Link to={`/admin/apps/${v.app_id}/versions`}>返回应用版本列表</Link>
      {cmd.feedback}
      <Panel>
        <h2>版本说明</h2>
        <Form
          key={v.revision}
          submit={(f) =>
            void cmd.run("version-edit", () =>
              write(
                "/api/v1/versions/{id}",
                "patch",
                {
                  display_name: text(f, "display_name"),
                  mode: v.mode,
                  release_notes: text(f, "release_notes"),
                },
                { id: v.id, revision: v.revision },
              ),
            )
          }
        >
          <Field
            name="display_name"
            label="版本名称"
            defaultValue={v.display_name}
            required
          />
          <label>
            发布说明
            <TextArea
              name="release_notes"
              defaultValue={v.release_notes}
              maxLength={10000}
            />
          </label>
          <Button disabled={cmd.pending}>保存说明</Button>
        </Form>
      </Panel>
      <Panel>
        <h2>创建平台发布修订</h2>
        <p>
          发布后文件集合永久冻结。替换安装包请创建新修订。Debug
          始终受限，Release 可明确选择公开副本。
        </p>
        <div className="field">
          <Select
            label="目标平台"
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value as "android" | "ios");
              setSelected([]);
            }}
          >
            <option value="android">Android</option>
            <option value="ios">iOS</option>
          </Select>
        </div>
        {v.mode === "release" && (
          <StorageChoice
            appId={v.app_id}
            mode="public"
            value={publicStorage}
            onChange={setPublicStorage}
          />
        )}
        {publicStorage && (
          <Notice>
            选择公开后，任何人都可取得发布副本。下架会尝试删除源站副本，无法收回已下载或被第三方复制的文件。
          </Notice>
        )}
        {filters.search}
        <ErrorBox error={packages.error} />
        {packages.data?.items
          .filter(
            (p) =>
              p.platform === platform &&
              p.mode === v.mode &&
              p.state === "ready",
          )
          .map((p) => (
            <label key={p.id}>
              <input
                type="checkbox"
                checked={selected.includes(p.id)}
                onChange={(e) =>
                  setSelected(
                    e.target.checked
                      ? [...selected, p.id]
                      : selected.filter((id) => id !== p.id),
                  )
                }
              />
              {p.file_name} · {p.version_name} ({p.build_number})
            </label>
          ))}
        <Pager data={packages.data} {...filters} />
        <p>已选择 {selected.length} 个文件（跨页保留）。</p>
        <Button
          type="button"
          disabled={cmd.pending || !selected.length}
          onClick={() =>
            void cmd.run(
              `publication-create-${v.id}-${platform}-${publicStorage}-${selected.join(",")}`,
              (key) =>
                write(
                  "/api/v1/versions/{id}/publications",
                  "post",
                  {
                    platform,
                    package_ids: selected,
                    public_storage_id: publicStorage || null,
                  },
                  { id: v.id, key },
                ),
              () => setSelected([]),
            )
          }
        >
          创建发布草稿
        </Button>
      </Panel>
      <ErrorBox error={publications.error} />
      {publications.data?.items.map((p) => (
        <Publication key={p.id} publication={p} />
      ))}
      <Pager
        data={publications.data}
        page={publicationPage}
        setPage={setPublicationPage}
      />
    </>
  );
}
function Publication({
  publication: p,
}: {
  publication: DTO<"PublicationInfo">;
}) {
  const cmd = useCommand();
  const accessPending = ["publishing", "reclaiming", "reclaim_failed"].includes(
    p.access_state || "",
  );
  const action = (
    verb: "publish" | "unpublish" | "archive" | "restore",
    label: string,
  ) =>
    void cmd.run(
      `publication-${verb}`,
      () =>
        write(`/api/v1/publications/{id}/${verb}`, "post", undefined, {
          id: p.id,
          revision: p.revision,
        }),
      undefined,
      p.public_storage_id && ["publish", "unpublish"].includes(verb)
        ? `${label}请求已接受，请查看公开副本访问任务结果。`
        : `已${label}。`,
      `${label}此 ${p.platform} ${p.mode} 发布？共 ${p.package_ids.length} 个文件；修订号 ${p.revision}。${verb === "publish" ? (p.public_storage_id ? "公开副本将允许任何人下载。" : "仅向已验证租户成员提供下载。") : verb === "unpublish" ? (p.public_storage_id ? "停止新授权并执行源站访问收回，任务失败时旧公开地址仍可能可访问。" : "停止新下载授权，已有链接最多仍可使用 5 分钟。") : "恢复不会自动发布。"}`,
    );
  return (
    <Panel>
      <h2>
        {p.platform} · {states[p.state]}
      </h2>
      <p>
        {p.package_ids.length} 个文件 · 修订 {p.revision} ·{" "}
        {p.file_set_frozen ? "文件集合已冻结" : "草稿文件集合"}
      </p>
      {cmd.feedback}
      <p>
        访问状态：
        {
          (
            {
              private: "私有",
              publishing: "公开副本生成中",
              public: "公开可读",
              reclaiming: "访问收回中",
              reclaim_failed: "访问收回失败",
              reclaimed: "源站访问已收回",
              publish_failed: "公开发布失败，副本已清理",
            } as Record<string, string>
          )[p.access_state || "private"]
        }
      </p>
      {p.access_error && <p role="alert">{p.access_error}</p>}
      {p.access_task_id && (
        <Link to={`/admin/tasks/${p.access_task_id}`}>查看访问任务</Link>
      )}
      <DefaultReleaseControl publication={p} />
      {p.access_state === "reclaim_failed" && (
        <Button
          disabled={cmd.pending}
          onClick={() =>
            void cmd.run("reclaim", () =>
              write(
                "/api/v1/publications/{id}/retry-access",
                "post",
                undefined,
                { id: p.id, revision: p.revision },
              ),
            )
          }
        >
          重试访问收回
        </Button>
      )}
      <div className="toolbar">
        {!accessPending && ["draft", "unpublished"].includes(p.state) && (
          <Button
            disabled={cmd.pending}
            onClick={() => action("publish", "发布")}
          >
            发布
          </Button>
        )}
        {p.state === "published" && (
          <>
            <Link to={`/releases/${p.id}`}>查看分发页面</Link>
            <Button
              disabled={cmd.pending}
              onClick={() => action("unpublish", "下架")}
            >
              下架
            </Button>
          </>
        )}
        {!accessPending && ["draft", "unpublished"].includes(p.state) && (
          <Button
            disabled={cmd.pending}
            onClick={() => action("archive", "归档")}
          >
            归档
          </Button>
        )}
        {p.state === "archived" && (
          <Button
            disabled={cmd.pending}
            onClick={() => action("restore", "恢复为草稿")}
          >
            恢复为草稿
          </Button>
        )}
      </div>
    </Panel>
  );
}

export function PublishedReleasesPage() {
  const session = useSession();
  const [platform, setPlatform] = useState("");
  const [names, setNames] = useState({ app_name: "", version_name: "" });
  const [nameDraft, setNameDraft] = useState(names);
  const filters = useFilters("搜索应用或版本名称…");
  const q = useQuery({
    queryKey: [
      "published-releases",
      session.data?.viewer_key,
      filters.page,
      filters.q,
      platform,
      names,
    ],
    queryFn: () =>
      read("/api/v1/catalog/publications", {
        query: {
          page: filters.page,
          q: filters.q,
          platform: platform || undefined,
          app_name: names.app_name || undefined,
          version_name: names.version_name || undefined,
        },
      }),
  });
  return (
    <>
      <Title description="仅展示当前账号有权下载的已发布版本。">版本下载</Title>
      <Link to="/">GitHub Debug 下载</Link>
      <p>
        <Link to="/login?return_to=%2Freleases">登录飞书查看受限版本</Link>
      </p>
      <div className="field">
        <Select
          label="平台"
          value={platform}
          onChange={(e) => {
            setPlatform(e.target.value);
            filters.setPage(1);
          }}
        >
          <option value="">全部平台</option>
          <option value="android">Android</option>
          <option value="ios">iOS</option>
        </Select>
      </div>
      <Form
        submit={() => {
          setNames(nameDraft);
          filters.setPage(1);
        }}
      >
        <fieldset>
          <legend>按应用和版本筛选</legend>
          <label>
            应用名称
            <input
              name="app_name"
              type="search"
              maxLength={100}
              value={nameDraft.app_name}
              onChange={(e) =>
                setNameDraft({ ...nameDraft, app_name: e.target.value })
              }
            />
          </label>
          <label>
            版本名称
            <input
              name="version_name"
              type="search"
              maxLength={100}
              value={nameDraft.version_name}
              onChange={(e) =>
                setNameDraft({ ...nameDraft, version_name: e.target.value })
              }
            />
          </label>
          <Button>应用筛选</Button>
          <Button
            type="button"
            onClick={() => {
              setNames({ app_name: "", version_name: "" });
              setNameDraft({ app_name: "", version_name: "" });
              setPlatform("");
              filters.reset();
            }}
          >
            清空筛选
          </Button>
        </fieldset>
      </Form>
      {filters.search}
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.data && !q.data.items.length && <Empty>暂无可下载版本。</Empty>}
      {q.data?.items.map((p) => (
        <Panel key={p.id}>
          <h2>
            <Link to={`/releases/${p.id}`}>
              {p.app_name} · {p.version_name}
            </Link>
          </h2>
          <p>
            {p.platform} · {p.mode} · {date(p.published_at)}
            {p.is_default && " · 默认展示"}
          </p>
        </Panel>
      ))}
      <Pager data={q.data} {...filters} />
    </>
  );
}
export function PublishedReleasePage() {
  const session = useSession();
  const { id = "" } = useParams();
  return (
    <PublishedReleaseContent
      key={`${session.data?.viewer_key}:${id}`}
      id={id}
      viewerKey={session.data?.viewer_key}
    />
  );
}
function PublishedReleaseContent({
  id,
  viewerKey,
}: {
  id: string;
  viewerKey?: string;
}) {
  const cmd = useCommand();
  const [link, setLink] = useState<DTO<"PublicationDownloadGrant">>();
  const q = useQuery({
    queryKey: ["published-release", viewerKey, id],
    queryFn: () => read("/api/v1/catalog/publications/{id}", { id }),
  });
  if (q.isPending) return <Loading />;
  if (!q.data)
    return (
      <>
        <ErrorBox error={q.error} />
        <Link to={`/login?return_to=${encodeURIComponent(`/releases/${id}`)}`}>
          登录飞书查看此版本
        </Link>
      </>
    );
  const p = q.data;
  return (
    <>
      <Title>{`${p.app_name} · ${p.version_name}`}</Title>
      <Link to="/releases">返回版本列表</Link>
      <p>
        {p.platform} · {p.mode} · {date(p.published_at)}
      </p>
      <p style={{ whiteSpace: "pre-wrap" }}>{p.release_notes}</p>
      {p.platform === "ios" && (
        <Notice>
          IPA 下载只代表取得文件，不代表设备可直接安装；此入口不是 TestFlight。
        </Notice>
      )}
      {cmd.feedback}
      {p.files.map((f) => (
        <Panel key={f.id}>
          <h2>{f.file_name}</h2>
          <p>
            {f.version_name} ({f.build_number}) ·{" "}
            {(f.size_bytes / 1024 / 1024).toFixed(2)} MiB
          </p>
          <p>{f.signature_status}</p>
          <Button
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run(
                `download-${f.id}`,
                () =>
                  write(
                    "/api/v1/catalog/publications/{id}/grants",
                    "post",
                    { package_id: f.id },
                    { id },
                  ),
                setLink,
                "下载链接已生成。",
              )
            }
          >
            获取下载链接
          </Button>
        </Panel>
      ))}
      {link && (
        <Notice>
          <a href={link.url} rel="noreferrer">
            开始下载
          </a>
          <p>
            {link.expires_at
              ? `链接有效至 ${date(link.expires_at)}，过期后请重新获取；请勿转发短期下载链接。`
              : "此为公开副本，任何取得地址的人均可下载；源站将在下架收回任务完成后停止提供该副本。"}
          </p>
        </Notice>
      )}
    </>
  );
}
