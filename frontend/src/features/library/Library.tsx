import { Select, DateInput, TextArea } from "../../shared/ui/FormControls";
import { useEffect, useRef, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { ApiError, read, write, type DTO } from "../../shared/api/http";
import { StorageChoice } from "./Storage";
import { DefaultReleaseControl, PackageManagement } from "./Management";
import { Badge, Button, Input, Panel, PageTabs, Notice } from "../../shared/ui/controls";
import "./publications.css";
import {
  Empty,
  ErrorBox,
  Field,
  Form,
  Loading,
  Pager,
  Title,
  date,
  size,
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
      <Title description="将 APK / IPA 上传到绑定的 COS 存储桶，解析并校验包标识后入库。入库不会自动发布。">
        安装包
      </Title>
      <PageTabs />
      <Uploader
        appId={id}
        uploads={uploads.data?.items ?? []}
        loading={uploads.isPending}
        failed={uploads.isError}
      />
      <Panel>
        <h2>从 COS 导入</h2>
        <p className="muted">
          批量扫描、解析 manifest 并导入 Debug / Release 安装包，请使用独立的导入页面。
        </p>
        <Link to={`/admin/apps/${id}/imports`}>打开 COS 安装包导入</Link>
      </Panel>
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
              <option value="cos">COS</option>
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
              {size(p.size_bytes)} ·{" "}
              {date(p.created_at)}
            </p>
            <p>{p.signature_status}</p>
            <p>
              状态：{states[p.state] || p.state} · 来源：
              {p.source_kind === "cos"
                ? "COS"
                : p.source_kind === "github"
                  ? "历史 GitHub（兼容）"
                  : "手工上传"}
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
            分片。上传会写入当前模式绑定的 COS 存储桶；刷新后重新选择原文件可续传，且必须先在应用设置配置对应平台和模式的包标识。
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
              appChannel={mode}
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

type ImportCandidate = DTO<"CosObjectCandidate"> & {
  channel: "debug" | "release";
};

function channelLabel(channel: "debug" | "release") {
  return channel === "debug" ? "Debug" : "Release";
}

function suggestedChannel(key: string, boundChannel: "debug" | "release") {
  const value = key.toLowerCase();
  if (/release|prod|store/.test(value)) return "release" as const;
  if (/debug|dev|snapshot|qa/.test(value)) return "debug" as const;
  return boundChannel;
}

function suggestedBuild(candidate: ImportCandidate) {
  const parts = candidate.key.split("/").filter(Boolean);
  const file = parts.at(-1) ?? candidate.key;
  const stem = file.replace(/\.[^.]+$/, "") || "manual-import";
  const parent = parts.at(-2);
  const buildNumber = /^\d+$/.test(stem) ? stem : parent && /^\d+$/.test(parent) ? parent : stem;
  const version = parent && parent !== buildNumber ? parent : stem;
  return {
    version,
    build_number: buildNumber,
    commit_sha: "manual-import",
    workflow_run_id: "manual-import",
    created_at: new Date().toISOString(),
  } satisfies DTO<"CosPackageBuild">;
}

function isMissingBinding(error: unknown) {
  return error instanceof ApiError && error.detail.code === "APP_STORAGE_NOT_BOUND";
}

export function PackageImportPage() {
  const { id = "" } = useParams();
  const [resolved, setResolved] = useState<Record<string, ImportCandidate>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [modeOverrides, setModeOverrides] = useState<Record<string, "debug" | "release">>({});
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const channels = ["debug", "release"] as const;
  const queries = useQueries({
    queries: channels.map((channel) => ({
      queryKey: ["cos-package-objects", id, channel, "import-page"],
      queryFn: () =>
        read("/api/v1/apps/{id}/package-ingestions/cos-objects", {
          id,
          query: { channel, page_size: 100 },
        }),
        refetchOnMount: "always" as const,
    })),
  });
  const loading = queries.some((query) => query.isPending);
  const blockingError = queries.find((query) => query.error && !isMissingBinding(query.error))?.error;
  const candidates: ImportCandidate[] = channels.flatMap((channel, index) =>
    (queries[index]?.data?.items ?? []).map((item) => ({ ...item, channel })),
  );
  const merged = candidates.map((candidate) => resolved[`${candidate.channel}:${candidate.key}`] ?? candidate);
  const ready = merged.filter((candidate) => candidate.sha256 && candidate.manifest_key && candidate.manifest_sha256);
  const selectableKeys = ready.map((candidate) => `${candidate.channel}:${candidate.key}`);
  const selectedReadyCount = selectableKeys.filter((key) => selected.includes(key)).length;
  const allReadySelected = selectableKeys.length > 0 && selectedReadyCount === selectableKeys.length;
  const someReadySelected = selectedReadyCount > 0 && !allReadySelected;
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someReadySelected;
  }, [someReadySelected]);

  async function resolveAll() {
    setBusy(true);
    setProgress("正在读取对象摘要与 manifest…");
    const next: Record<string, ImportCandidate> = { ...resolved };
    try {
      for (const candidate of merged) {
        if (candidate.sha256 && candidate.manifest_key && candidate.manifest_sha256) continue;
        const result = await read("/api/v1/apps/{id}/package-ingestions/cos-objects", {
          id,
          query: { channel: candidate.channel, page_size: 100, resolve_key: candidate.key },
        });
        const fresh = result.items.find((item) => item.key === candidate.key);
        if (fresh) next[`${candidate.channel}:${candidate.key}`] = { ...candidate, ...fresh };
      }
      setResolved(next);
      setProgress("解析完成。请检查导入模式后批量提交。 ");
    } catch (error) {
      setProgress(error instanceof Error ? error.message : "解析失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  async function importSelected() {
    const targets = merged.filter((candidate) => selected.includes(`${candidate.channel}:${candidate.key}`));
    if (!targets.length) return;
    setBusy(true);
    setProgress(`正在提交 0/${targets.length} 个导入任务…`);
    let completed = 0;
    const results = await Promise.allSettled(
      targets.map(async (candidate) => {
        const key = `${candidate.channel}:${candidate.key}`;
        const channel = modeOverrides[key] ?? suggestedChannel(candidate.key, candidate.channel);
        if (!candidate.sha256 || !candidate.manifest_key || !candidate.manifest_sha256)
          throw new Error(`${candidate.key} 尚未完成 manifest 解析`);
        const build = suggestedBuild(candidate);
        const result = await write(
          "/api/v1/apps/{id}/package-ingestions/import",
          "post",
          {
            channel,
            object_key: candidate.key,
            object_size: candidate.size,
            object_sha256: candidate.sha256,
            manifest_key: candidate.manifest_key,
            manifest_sha256: candidate.manifest_sha256,
            build,
            event_id: `manual-cos:${channel}:${candidate.sha256.slice(0, 24)}`,
          },
          { id, key: crypto.randomUUID() },
        );
        completed += 1;
        setProgress(`正在提交 ${completed}/${targets.length} 个导入任务…`);
        return result;
      }),
    );
    const failed = results.filter((result) => result.status === "rejected").length;
    setSelected([]);
    setBusy(false);
    setProgress(failed ? `已提交 ${targets.length - failed} 个，${failed} 个失败，请查看任务详情。` : `已提交 ${targets.length} 个导入任务。`);
  }

  return (
    <div className="app-tab-page package-import-page">
      <Title description="以绑定 COS 为唯一来源，批量扫描、解析 manifest 并导入 Debug 或 Release 安装包。">
        导入安装包
      </Title>
      <PageTabs />
      <Panel className="import-hero">
        <div className="section-heading">
          <div>
            <h2>扫描绑定存储桶</h2>
            <p className="muted">只读取此 App 已绑定的 Debug / Release 存储桶，不读取 GitHub Release。</p>
          </div>
          <Button type="button" className="primary" disabled={busy || loading || !merged.length} onClick={() => void resolveAll()}>
            {busy ? "处理中…" : "一键解析 manifest"}
          </Button>
        </div>
        <ErrorBox error={blockingError} />
        {queries.map((query, index) => {
          if (!query.error || !isMissingBinding(query.error)) return null;
          const channel = channels[index];
          if (!channel) return null;
          return (
            <Notice key={channel} role="status">
              <strong>{channelLabel(channel)} 尚未绑定存储桶</strong>
              <p>已跳过该通道；如需扫描，请先在应用设置中绑定对应的包源存储桶。</p>
              <Link to={`/admin/apps/${id}`}>去应用设置绑定 {channelLabel(channel)} 存储桶</Link>
            </Notice>
          );
        })}
        {loading && <Loading />}
        {progress && <Notice role="status">{progress}</Notice>}
        {!loading && !merged.length && <Empty>当前绑定桶下没有 APK、IPA 或 ZIP。请先上传构建产物。</Empty>}
        {!!merged.length && (
          <>
            <div className="import-toolbar">
              <div className="import-toolbar-selection">
                <label className="import-select-all">
                  <input
                    ref={selectAllRef}
                    type="checkbox"
                    checked={allReadySelected}
                    disabled={busy || !selectableKeys.length}
                    aria-label="选中全部可导入对象"
                    onChange={(event) => setSelected(event.target.checked ? selectableKeys : [])}
                  />
                  <span>选中全部</span>
                </label>
                <span className="muted">已解析 {ready.length}/{merged.length} 个对象 · 已选择 {selected.length} 个</span>
              </div>
              <Button type="button" disabled={busy || !selected.length} onClick={() => void importSelected()}>
                批量导入选中项
              </Button>
            </div>
            <div className="import-candidate-list">
              {merged.map((candidate) => {
                const key = `${candidate.channel}:${candidate.key}`;
                const checked = selected.includes(key);
                const mode = modeOverrides[key] ?? suggestedChannel(candidate.key, candidate.channel);
                const usable = Boolean(candidate.sha256 && candidate.manifest_key && candidate.manifest_sha256);
                return (
                  <div className={`import-candidate ${checked ? "is-selected" : ""}`} key={key}>
                    <label className="import-candidate-select">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={!usable || busy}
                        onChange={(event) => setSelected((current) => event.target.checked ? [...current, key] : current.filter((item) => item !== key))}
                      />
                      <span>
                        <strong>{candidate.key}</strong>
                        <small>{size(candidate.size)} · 来源 {channelLabel(candidate.channel)} · {usable ? "manifest 已解析" : "待解析"}</small>
                      </span>
                    </label>
                    <div className="import-candidate-actions">
                      <Select
                        aria-label={`${candidate.key} 导入模式`}
                        value={mode}
                        disabled={busy}
                        onChange={(event) => setModeOverrides((current) => ({ ...current, [key]: event.target.value as "debug" | "release" }))}
                      >
                        <option value="debug">导入为 Debug</option>
                        <option value="release">导入为 Release</option>
                      </Select>
                      <Badge className={usable ? "pass" : "fail"}>{usable ? "可导入" : "待解析"}</Badge>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </Panel>
      <CosReleaseInbox appId={id} />
      <Panel>
        <h2>导入约定</h2>
        <p>推荐目录：<code>android/&lt;buildNumber&gt;.zip</code>、<code>ios/&lt;buildNumber&gt;.zip</code>、<code>harmony/&lt;buildNumber&gt;.zip</code>。</p>
        <p className="muted">ZIP 内应包含唯一 APK / IPA、对应的 .sha256 和 build-info.json；扫描只负责发现和校验，最终仍由后台任务再次验证后入库。</p>
      </Panel>
    </div>
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
  const releaseVersions = useQuery({
    queryKey: ["release-version-overview", id],
    queryFn: () =>
      read("/api/v1/apps/{id}/versions", {
        id,
        query: { page: 1, page_size: 100 },
      }),
  });
  const publicationQueries = useQueries({
    queries: (releaseVersions.data?.items ?? []).map((version) => ({
      queryKey: ["release-overview-publications", version.id],
      queryFn: () =>
        read("/api/v1/versions/{id}/publications", {
          id: version.id,
          query: { page: 1, page_size: 100 },
        }),
    })),
  });
  const versionNames = new Map(
    (releaseVersions.data?.items ?? []).map((version) => [version.id, version.display_name]),
  );
  const publishedReleases = publicationQueries
    .flatMap((query) => query.data?.items ?? [])
    .filter((publication) => publication.mode === "release" && publication.state === "published")
    .sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""));
  const [releaseSearch, setReleaseSearch] = useState("");
  const activeRelease = publishedReleases[0];
  const otherReleases = publishedReleases.slice(1).filter((publication) => {
    const haystack = `${versionNames.get(publication.version_id) ?? ""} ${publication.platform}`.toLowerCase();
    return !releaseSearch || haystack.includes(releaseSearch.toLowerCase());
  });
  return (
    <div className="app-tab-page versions-page">
      <Title description="版本可包含 Android 与 iOS 的独立发布修订。上传入库后，需要在这里显式发布。">
        版本发布
      </Title>
      <PageTabs />
      {cmd.feedback}
      <ReleaseOverview
        active={activeRelease}
        others={otherReleases}
        versionNames={versionNames}
        search={releaseSearch}
        onSearch={setReleaseSearch}
        loading={releaseVersions.isPending || publicationQueries.some((query) => query.isPending)}
      />
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

function ReleaseOverview({
  active,
  others,
  versionNames,
  search,
  onSearch,
  loading,
}: {
  active?: DTO<"PublicationInfo">;
  others: DTO<"PublicationInfo">[];
  versionNames: Map<string, string>;
  search: string;
  onSearch: (value: string) => void;
  loading: boolean;
}) {
  const latestUrl = active ? `${window.location.origin}/releases/${active.id}` : "";
  return (
    <Panel className="release-overview">
      <div className="section-heading">
        <div>
          <h2>Release 分发概览</h2>
          <p className="muted">COS 是唯一来源；这里仅展示已发布的 Release 访问入口。</p>
        </div>
        <Badge className={active ? "pass" : "badge"}>{active ? "1 个启用版本" : "尚未启用"}</Badge>
      </div>
      {loading && <Loading />}
      {!loading && !active && <Empty>暂无已启用的 Release。发布一个版本后，访问 URL 会显示在这里。</Empty>}
      {active && (
        <div className="release-active-card">
          <div>
            <small>最新版本 URL</small>
            <p><Link to={`/releases/${active.id}`}>{latestUrl}</Link></p>
          </div>
          <div className="release-active-meta">
            <strong>{versionNames.get(active.version_id) ?? "Release"}</strong>
            <span>{active.platform.toUpperCase()} · 启用中 · {active.published_at ? date(active.published_at) : "—"}</span>
          </div>
        </div>
      )}
      {!!others.length && (
        <div className="release-archive-list">
          <div className="section-heading">
            <h3>其他使用中的 Release</h3>
            <Input
              type="search"
              aria-label="搜索其他 Release"
              placeholder="搜索版本或平台"
              value={search}
              onChange={(event) => onSearch(event.target.value)}
            />
          </div>
          {others.map((publication) => (
            <div className="release-archive-row" key={publication.id}>
              <Link to={`/releases/${publication.id}`}>
                {versionNames.get(publication.version_id) ?? "Release"}
              </Link>
              <span>{publication.platform.toUpperCase()} · {publication.published_at ? date(publication.published_at) : "—"}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function CosReleaseInbox({ appId }: { appId: string }) {
  const cmd = useCommand();
  const ingestions = useQuery({
    queryKey: ["cos-release-ingestions", appId],
    queryFn: () =>
      read("/api/v1/apps/{id}/package-ingestions", {
        id: appId,
        query: { page: 1, page_size: 50, channel: "release" },
      }),
    refetchInterval: 5000,
  });
  const items = ingestions.data?.items ?? [];
  const pending = items.filter((item) => item.state === "pending_publish");
  const failed = items.filter((item) => item.state === "failed");
  return (
    <Panel className="cos-release-inbox">
      <h2>COS Release 待发布</h2>
      <p>
        GitHub Actions 只负责构建并上传 COS。校验通过的 Release 会停在这里，确认后才会进入版本发布列表。
      </p>
      {cmd.feedback}
      <ErrorBox error={ingestions.error} />
      {ingestions.isPending && <Loading />}
      {!ingestions.isPending && !ingestions.isError && !pending.length && !failed.length && (
        <p>暂无待发布的 COS Release。</p>
      )}
      {pending.length > 0 && <h3>待确认发布（{pending.length}）</h3>}
      {pending.map((item) => (
        <div className="cos-release-inbox-item" key={item.id}>
          <div>
            <strong>{item.build.version}</strong>
            <span>
              {" "}
              · build {item.build.build_number} · {item.object_key}
            </span>
            <p>
              事件 {item.event_id} · 上传于 {date(item.created_at)}
            </p>
            <dl className="cos-release-inbox-details">
              <div>
                <dt>Commit</dt>
                <dd>{item.build.commit_sha}</dd>
              </div>
              <div>
                <dt>Workflow run</dt>
                <dd>{item.build.workflow_run_id}</dd>
              </div>
              <div>
                <dt>对象大小</dt>
                <dd>{size(item.object_size)}</dd>
              </div>
              <div>
                <dt>对象 SHA-256</dt>
                <dd>{item.object_sha256}</dd>
              </div>
              <div>
                <dt>Manifest</dt>
                <dd>{item.manifest_key}</dd>
              </div>
              <div>
                <dt>Manifest SHA-256</dt>
                <dd>{item.manifest_sha256}</dd>
              </div>
            </dl>
          </div>
          <Button
            type="button"
            className="primary"
            disabled={cmd.pending || item.publication_revision == null}
            onClick={() =>
              void cmd.run(
                "publish-cos-release-" + item.id,
                () =>
                  write("/api/v1/package-ingestions/{id}/publish", "post", undefined, {
                    id: item.id,
                    revision: item.publication_revision ?? undefined,
                  }),
                undefined,
                "COS Release 已确认发布。",
                "确认发布这个 COS Release？发布前会再次校验 COS 对象内容。",
              )
            }
          >
            确认发布
          </Button>
        </div>
      ))}
      {failed.length > 0 && <h3>处理失败（{failed.length}）</h3>}
      {failed.map((item) => (
        <div className="cos-release-inbox-item failed" key={item.id}>
          <div>
            <strong>{item.build.version}</strong>
            <span>
              {" "}
              · build {item.build.build_number} · {item.object_key}
            </span>
            <p>
              {item.error_code || "INGESTION_FAILED"} · {item.error_message || "入库失败，请重试"}
            </p>
          </div>
          <Button
            type="button"
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run(
                "retry-cos-release-" + item.id,
                () => write("/api/v1/package-ingestions/{id}/retry", "post", undefined, { id: item.id }),
                undefined,
                "已重新排队 COS Release 入库。",
              )
            }
          >
            重试入库
          </Button>
        </div>
      ))}
    </Panel>
  );
}

export function CosPackageImportForm({
  appId,
  channel,
}: {
  appId: string;
  channel: "debug" | "release";
}) {
  const cmd = useCommand();
  const [open, setOpen] = useState(false);
  const [selectedKey, setSelectedKey] = useState("");
  const [resolveKey, setResolveKey] = useState("");
  const objects = useQuery({
    queryKey: ["cos-package-objects", appId, channel, resolveKey],
    queryFn: () =>
      read("/api/v1/apps/{id}/package-ingestions/cos-objects", {
        id: appId,
        query: {
          channel,
          page_size: 50,
          resolve_key: resolveKey || undefined,
        },
      }),
    enabled: open,
    staleTime: 15_000,
  });
  const selected = objects.data?.items.find((item) => item.key === selectedKey);
  return (
    <details
      className="cos-package-import"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        通知丢失？从已绑定 COS 导入 {channel === "debug" ? "Debug" : "Release"}
      </summary>
      <p>
        仅填写已上传到当前 App/{channel} 存储绑定的对象元数据。Fuma 会重新读取对象、校验摘要和 manifest，不能通过此表单上传或绕过校验。
      </p>
      {cmd.feedback}
      <div className="cos-package-object-picker">
        <strong>绑定对象</strong>
        <ErrorBox error={objects.error} />
        {objects.isPending && <Loading />}
        {!objects.isPending && !objects.isError && !objects.data?.items.length && (
          <p>当前绑定前缀下没有找到 APK、IPA 或 ZIP。</p>
        )}
        {objects.data?.items.map((item) => {
          const usable = Boolean(
            item.sha256 && item.manifest_key && item.manifest_sha256,
          );
          return (
            <div className="cos-package-object" key={item.key}>
              <div>
                <code>{item.key}</code>
                <small>
                  {size(item.size)}
                  {usable ? " · manifest 已找到" : " · 缺少摘要或 manifest"}
                </small>
              </div>
              <Button
                type="button"
                disabled={cmd.pending}
                onClick={() => {
                  setSelectedKey(item.key);
                  if (!usable) setResolveKey(item.key);
                }}
              >
                {selectedKey === item.key && !usable
                  ? "正在解析…"
                  : selectedKey === item.key
                    ? "已选择"
                    : item.sha256
                      ? "选择"
                      : "解析摘要"}
              </Button>
            </div>
          );
        })}
      </div>
      <Form
        className="cos-package-import-fields"
        key={selected?.key ?? "manual"}
        submit={(f) => {
          const objectSize = Number(text(f, "object_size"));
          const body: DTO<"CosPackageImportRequest"> = {
            channel,
            object_key: text(f, "object_key"),
            object_size: objectSize,
            object_sha256: text(f, "object_sha256"),
            manifest_key: text(f, "manifest_key"),
            manifest_sha256: text(f, "manifest_sha256"),
            event_id: text(f, "event_id") || undefined,
            build: {
              version: text(f, "version"),
              build_number: text(f, "build_number"),
              commit_sha: text(f, "commit_sha"),
              workflow_run_id: text(f, "workflow_run_id"),
              created_at: text(f, "created_at"),
            },
          };
          void cmd.run(
            `cos-import-${channel}`,
            (key) =>
              write("/api/v1/apps/{id}/package-ingestions/import", "post", body, {
                id: appId,
                key,
              }),
            undefined,
            `${channel === "debug" ? "Debug" : "Release"} COS 导入已排队。`,
          );
        }}
      >
        <Field
          name="object_key"
          label="安装包对象 key"
          defaultValue={selected?.key}
          required
          maxLength={600}
        />
        <Field
          name="object_size"
          label="对象大小（字节）"
          type="number"
          min={1}
          defaultValue={selected?.size}
          required
        />
        <Field
          name="object_sha256"
          label="对象 SHA-256"
          defaultValue={selected?.sha256 ?? undefined}
          required
          pattern="^[0-9a-fA-F]{64}$"
          validationMessage="请输入 64 位十六进制 SHA-256。"
        />
        <Field
          name="manifest_key"
          label="Manifest 对象 key"
          defaultValue={selected?.manifest_key ?? undefined}
          required
          maxLength={600}
        />
        <Field
          name="manifest_sha256"
          label="Manifest SHA-256"
          defaultValue={selected?.manifest_sha256 ?? undefined}
          required
          pattern="^[0-9a-fA-F]{64}$"
          validationMessage="请输入 64 位十六进制 SHA-256。"
        />
        <Field name="version" label="版本号" required maxLength={100} />
        <Field name="build_number" label="Build number" required maxLength={100} />
        <Field name="commit_sha" label="Commit SHA" required minLength={7} maxLength={100} />
        <Field name="workflow_run_id" label="Workflow run ID" required maxLength={100} />
        <Field
          name="created_at"
          label="构建时间（ISO 8601）"
          required
          defaultValue={new Date().toISOString()}
          help="例如 2026-10-17T10:00:00Z。"
        />
        <Field name="event_id" label="事件 ID（可选）" maxLength={128} />
        <Button type="submit" className="primary" disabled={cmd.pending}>
          提交 COS 导入
        </Button>
      </Form>
    </details>
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
  const [appId, setAppId] = useState("");
  const [versionName, setVersionName] = useState("");
  const [versionDraft, setVersionDraft] = useState("");
  const apps = useQuery({
    queryKey: ["publication-apps", session.data?.viewer_key],
    enabled: session.isSuccess,
    queryFn: async () => {
      const items: DTO<"PublicationApp">[] = [];
      for (let page = 1; ; page++) {
        const result = await read(
          session.data?.authenticated
            ? "/api/v1/catalog/apps"
            : "/api/v1/catalog/publication-apps",
          { query: { page, page_size: 100 } },
        );
        items.push(...result.items);
        if (!result.items.length || items.length >= result.total) return items;
      }
    },
  });
  const selectedApp =
    apps.data?.find((app) => app.id === appId)?.id ?? apps.data?.[0]?.id ?? "";
  const filters = useFilters("搜索应用或版本名称…");
  const q = useQuery({
    queryKey: [
      "published-releases",
      session.data?.viewer_key,
      filters.page,
      filters.q,
      platform,
      selectedApp,
      versionName,
    ],
    enabled: apps.isSuccess && !!selectedApp,
    queryFn: () =>
      read("/api/v1/catalog/publications", {
        query: {
          page: filters.page,
          q: filters.q,
          platform: platform || undefined,
          app_id: selectedApp,
          version_name: versionName || undefined,
        },
      }),
  });
  return (
    <>
      <Title description="仅展示当前账号有权下载的已发布版本。">版本下载</Title>
      <Link to="/">Debug 下载</Link>
      {session.isSuccess && !session.data?.authenticated && (
        <p>
          <Link to="/login?return_to=%2Freleases">登录飞书查看受限版本</Link>
        </p>
      )}
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
        className="publication-name-filters"
        submit={() => {
          setVersionName(versionDraft);
          filters.setPage(1);
        }}
      >
        <fieldset>
          <legend>按应用和版本筛选</legend>
          <div className="publication-name-fields">
            <div className="field">
              <Select
                label="应用"
                name="app_id"
                value={selectedApp}
                disabled={!apps.data?.length}
                onChange={(e) => {
                  setAppId(e.target.value);
                  filters.setPage(1);
                }}
              >
                {!apps.data?.length && (
                  <option value="">
                    {apps.isPending ? "正在加载应用…" : "暂无可选应用"}
                  </option>
                )}
                {apps.data?.map((app) => (
                  <option key={app.id} value={app.id}>
                    {app.name}
                  </option>
                ))}
              </Select>
            </div>
            <Field
              label="版本名称"
              name="version_name"
              type="search"
              placeholder="输入版本名称"
              maxLength={100}
              value={versionDraft}
              onChange={(e) => setVersionDraft(e.target.value)}
            />
            <div className="publication-filter-actions">
              <Button className="primary">应用筛选</Button>
              <Button
                type="button"
                onClick={() => {
                  setAppId("");
                  setVersionName("");
                  setVersionDraft("");
                  setPlatform("");
                  filters.reset();
                }}
              >
                清空筛选
              </Button>
            </div>
          </div>
        </fieldset>
      </Form>
      {filters.search}
      <ErrorBox error={apps.error || q.error} />
      {(apps.isPending || (selectedApp && q.isPending)) && <Loading />}
      {apps.isSuccess && !selectedApp && <Empty>暂无可选应用。</Empty>}
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
            {size(f.size_bytes)}
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
