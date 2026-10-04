import { Select } from "../../shared/ui/FormControls";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { Button, Panel } from "../../shared/ui/controls";
import { ErrorBox, Pager, useCommand } from "../../shared/ui/common";
import { StorageChoice } from "./Storage";

export function GitHubPackageImport({
  appId,
  release,
  selected,
}: {
  appId: string;
  release: DTO<"GitHubRelease">;
  selected: string[];
}) {
  const cmd = useCommand();
  const [mode, setMode] = useState<"debug" | "release">("release");
  const [storage, setStorage] = useState("default");
  const [version, setVersion] = useState("");
  const [page, setPage] = useState(1);
  const [results, setResults] = useState<
    { name: string; upload?: DTO<"UploadSession">; error?: string }[]
  >([]);
  const versions = useQuery({
    queryKey: ["import-versions", appId, page],
    queryFn: () =>
      read("/api/v1/apps/{id}/versions", {
        id: appId,
        query: { page, page_size: 100 },
      }),
  });
  return (
    <Panel>
      <h3>导入安装包库</h3>
      <p>
        使用上方勾选的 APK / IPA。重新验证来源、解析包标识并保存私有原件；Debug
        / Release
        是包的模式，均可入库。不会自动发布或通知。每个附件单独显示任务，失败不影响已接受的附件。
      </p>
      <fieldset
        disabled={cmd.pending}
        style={{ border: 0, padding: 0, minWidth: 0 }}
      >
        <div className="field">
          <Select
            label="目标模式"
            value={mode}
            onChange={(e) => {
              setMode(e.target.value as "debug" | "release");
              setVersion("");
            }}
          >
            <option value="release">Release</option>
            <option value="debug">Debug</option>
          </Select>
        </div>
        <StorageChoice
          appId={appId}
          mode="private"
          value={storage}
          onChange={setStorage}
        />
        <div className="field">
          <Select
            label="目标版本"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          >
            <option value="">仅入库，稍后组织版本</option>
            {versions.data?.items
              .filter((v) => v.mode === mode)
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.display_name}
                </option>
              ))}
          </Select>
        </div>
        {versions.data && versions.data.total > 100 && (
          <Pager data={versions.data} page={page} setPage={setPage} />
        )}
        <ErrorBox error={versions.error} />
      </fieldset>
      {cmd.feedback}
      <Button
        className="primary"
        disabled={cmd.pending || !selected.length || release.draft}
        onClick={() =>
          void cmd.run(
            JSON.stringify([
              "formal-import",
              release.id,
              selected,
              mode,
              version,
              storage,
            ]),
            async (key) => {
              const result = [];
              for (const assetId of selected) {
                const name =
                  release.assets.find((a) => a.id === assetId)?.name || assetId;
                try {
                  const upload = await write(
                    "/api/v1/apps/{id}/package-imports",
                    "post",
                    {
                      release_id: release.id,
                      asset_id: assetId,
                      mode,
                      version_id: version || null,
                      ...(storage !== "default"
                        ? { storage_location_id: storage || null }
                        : {}),
                    },
                    { id: appId, key: `${key}-${assetId}` },
                  );
                  result.push({ name, upload });
                } catch (error) {
                  result.push({
                    name,
                    error:
                      error instanceof Error
                        ? error.message
                        : "提交失败，请重试",
                  });
                }
                setResults([...result]);
              }
              return result;
            },
            undefined,
            "导入请求已处理，请查看逐附件结果。",
          )
        }
      >
        解析入库 {selected.length || ""} 个附件（不发布）
      </Button>
      {results.map((row) => (
        <div key={row.name}>
          <p>
            {row.name} · {row.error || "已接受"}
          </p>
          {row.upload?.task_id && (
            <Link to={`/admin/tasks/${row.upload.task_id}`}>查看入库任务</Link>
          )}
        </div>
      ))}
      <Link to={`/admin/apps/${appId}/packages`}>查看安装包与导入状态</Link>
    </Panel>
  );
}

export function LegacyPersistence({ entry }: { entry: DTO<"DebugEntry"> }) {
  const cmd = useCommand();
  const [storage, setStorage] = useState("");
  const [available, setAvailable] = useState<string[]>([]);
  const [upload, setUpload] = useState<DTO<"UploadSession">>();
  const app = useQuery({
    queryKey: ["app", entry.app_id],
    queryFn: () => read("/api/v1/apps/{id}", { id: entry.app_id }),
    enabled: !entry.persistent_package_id,
  });
  const identifierReady = app.data?.allowed_package_ids.some(
    (item) => item.platform === entry.platform && item.mode === "debug",
  );
  if (entry.persistent_package_id)
    return (
      <Panel>
        <h3>已迁入私有原件存储</h3>
        <p>新授权使用已解析的私有文件；固定页面与旧链接保持兼容。</p>
        <Link to={`/admin/apps/${entry.app_id}/packages`}>查看解析包</Link>
      </Panel>
    );
  return (
    <Panel>
      <details>
        <summary>将旧版 Debug 分发迁入安装包库</summary>
        <p>
          迁移会重新下载来源并验证包标识与内容。成功后保留原条目 ID
          和页面，新的下载使用私有原件；失败继续使用旧缓存。请先配置 Debug
          包标识。此操作不创建版本或发布，也不会发送通知。
        </p>
        <ErrorBox error={app.error} />
        {app.isPending && <p role="status">正在检查应用包标识…</p>}
        {app.data && !identifierReady && (
          <p role="alert">
            尚未配置 {entry.platform === "android" ? "Android" : "iOS"} 的 Debug
            包标识。请先到{" "}
            <Link to={`/admin/apps/${entry.app_id}`}>应用设置</Link> 添加。
          </p>
        )}
        <StorageChoice
          appId={entry.app_id}
          mode="private"
          value={storage}
          onChange={setStorage}
          cloudOnly
          onAvailability={setAvailable}
        />
        {!!available.length && !available.includes(storage) && (
          <p>请选择一个可用私有云存储后开始迁移。</p>
        )}
        {cmd.feedback}
        <Button
          className="primary"
          disabled={
            cmd.pending || !available.includes(storage) || !identifierReady
          }
          onClick={() =>
            void cmd.run(
              `persist-${entry.id}-${storage}`,
              (key) =>
                write(
                  "/api/v1/debug-entries/{id}/persist",
                  "post",
                  { storage_location_id: storage },
                  { id: entry.id, key },
                ),
              setUpload,
              "迁移任务已创建。",
              "确认重新读取来源并迁入选定的私有存储？成功前保持旧下载入口。",
            )
          }
        >
          开始持久化迁移
        </Button>
        {upload?.task_id && (
          <Link to={`/admin/tasks/${upload.task_id}`}>查看迁移任务</Link>
        )}
      </details>
    </Panel>
  );
}
