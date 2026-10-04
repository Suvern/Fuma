import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import Select from "@douyinfe/semi-ui-19/lib/es/select";
import Table from "@douyinfe/semi-ui-19/lib/es/table";
import { read, write, type DTO } from "../../shared/api/http";
import { Badge, Button, Notice, Panel } from "../../shared/ui/controls";
import {
  Check,
  ErrorBox,
  Field,
  Form,
  Loading,
  TaskNotice,
  date,
  size,
  useCommand,
} from "../../shared/ui/common";

type Rules = DTO<"ReleaseMatchRules">;
type Draft = {
  include: string;
  exclude: string;
  tag: string;
  prerelease: Rules["prerelease"];
  auto: boolean;
  interval: number;
};
const splitPatterns = (value: string) =>
  value
    .split(/[,\n]+/)
    .map((v) => v.trim())
    .filter(Boolean);
const statusLabels = {
  disabled: "未启用",
  scheduled: "等待下次检查",
  paused: "已暂停：检查应用或连接状态",
  running: "正在检查并导入",
  failed: "上次任务有失败，等待下次重试",
};

export function ReleaseRules({
  appId,
  snapshotReady,
}: {
  appId: string;
  snapshotReady: boolean;
}) {
  const policy = useQuery({
    queryKey: ["release-policy", appId],
    queryFn: () =>
      read("/api/v1/apps/{id}/github/releases/policy", { id: appId }),
    refetchInterval: 10_000,
  });
  const [edited, setEdited] = useState<Draft>();
  const [preview, setPreview] = useState<DTO<"ReleaseImportPreview">>();
  const [task, setTask] = useState<DTO<"TaskAccepted">>();
  const command = useCommand();
  const saved = policy.data;
  if (!saved)
    return (
      <Panel>
        <ErrorBox error={policy.error} />
        {policy.isPending && <Loading />}
      </Panel>
    );
  const draft: Draft = edited ?? {
    include: saved.rules.asset_patterns.join(", "),
    exclude: saved.rules.exclude_patterns.join(", "),
    tag: saved.rules.tag_pattern,
    prerelease: saved.rules.prerelease,
    auto: saved.auto_enabled,
    interval: saved.interval_minutes,
  };
  const rules: Rules = {
    asset_patterns: splitPatterns(draft.include),
    exclude_patterns: splitPatterns(draft.exclude),
    tag_pattern: draft.tag.trim(),
    prerelease: draft.prerelease,
  };
  function change(patch: Partial<Draft>) {
    setEdited({ ...draft, ...patch });
    setPreview(undefined);
  }
  const valid =
    rules.asset_patterns.length > 0 &&
    rules.asset_patterns.length <= 20 &&
    rules.exclude_patterns.length <= 20 &&
    rules.tag_pattern.length > 0 &&
    [
      ...rules.asset_patterns,
      ...rules.exclude_patterns,
      rules.tag_pattern,
    ].every((p) => p.length <= 255);
  const result = saved.last_result;
  return (
    <Panel className="release-rules">
      <div className="section-heading">
        <div>
          <h2>按规则导入安装包</h2>
          <p className="muted">
            配置一次文件名规则，批量导入所有匹配的 Release 产物。
          </p>
        </div>
        <Badge>
          {saved.auto_enabled ? "自动同步已启用" : "自动同步未启用"}
        </Badge>
      </div>
      <Form
        submit={() =>
          void command.run(
            "release-policy-save",
            () =>
              write(
                "/api/v1/apps/{id}/github/releases/policy",
                "put",
                {
                  rules,
                  auto_enabled: draft.auto,
                  interval_minutes: draft.interval,
                },
                { id: appId, revision: saved.revision },
              ),
            () => setEdited(undefined),
            "规则已保存。",
          )
        }
      >
        <fieldset disabled={command.pending} className="release-rule-fields">
          <div className="release-rule-grid">
            <Field
              label="安装包文件名"
              required
              value={draft.include}
              maxLength={5119}
              placeholder="例如 joice-*-arm64.apk, *.ipa"
              onChange={(e) => change({ include: e.target.value })}
              help="多个规则用逗号分隔，命中任意一条即可。* 匹配任意字符，? 匹配一个字符，区分大小写。"
            />
            <Field
              label="排除文件名（可选）"
              value={draft.exclude}
              maxLength={5119}
              placeholder="例如 *unsigned*, *symbols*"
              onChange={(e) => change({ exclude: e.target.value })}
              help="排除规则优先，只导入应用支持的 APK / IPA。"
            />
            <Field
              label="Release Tag"
              required
              value={draft.tag}
              maxLength={255}
              onChange={(e) => change({ tag: e.target.value })}
              help="* 表示全部版本；例如 v* 或 debug-*。"
            />
            <label className="field">
              <span id={`rule-prerelease-${appId}`}>Release 类型</span>
              <Select
                aria-labelledby={`rule-prerelease-${appId}`}
                value={draft.prerelease}
                onChange={(value) =>
                  change({ prerelease: String(value) as Rules["prerelease"] })
                }
              >
                <Select.Option value="all">正式版本与预发布</Select.Option>
                <Select.Option value="exclude">仅正式版本</Select.Option>
                <Select.Option value="only">仅预发布</Select.Option>
              </Select>
              <small>草稿始终跳过。</small>
            </label>
          </div>
          <div className="release-auto-settings">
            <Check
              label="自动检查更新并导入匹配产物"
              checked={draft.auto}
              onChange={(e) => change({ auto: Boolean(e.target.checked) })}
            />
            {draft.auto && (
              <Field
                label="检查间隔（分钟）"
                type="number"
                min={5}
                max={1440}
                required
                value={draft.interval}
                onChange={(e) => change({ interval: Number(e.target.value) })}
              />
            )}
          </div>
          <p className="muted">
            启用后会先导入已有匹配产物，之后检查新 Release
            和附件更新；已有产物自动跳过，无需修改 GitHub Actions。导入到 Debug
            下载列表，文件在首次下载时缓存并校验。
          </p>
          <div className="toolbar">
            <Button
              type="button"
              disabled={!valid || !snapshotReady || command.pending}
              onClick={() =>
                void command.run(
                  "release-preview",
                  () =>
                    write(
                      "/api/v1/apps/{id}/github/releases/preview",
                      "post",
                      rules,
                      { id: appId },
                    ),
                  setPreview,
                  "匹配预览已更新。",
                )
              }
            >
              预览匹配产物
            </Button>
            <Button disabled={!valid || command.pending}>
              保存规则{draft.auto ? "并启用自动同步" : ""}
            </Button>
          </div>
        </fieldset>
      </Form>
      {!snapshotReady && (
        <Notice>
          先点击“同步
          Releases”获取仓库产物，随后即可预览；也可以保存并启用自动同步，由后台完成首次检查。
        </Notice>
      )}
      {command.feedback}
      <TaskNotice
        task={
          task ??
          (saved.last_task_id
            ? {
                task_id: saved.last_task_id,
                status_url: `/api/v1/tasks/${saved.last_task_id}`,
              }
            : undefined)
        }
      />
      {preview && (
        <div className="release-preview" aria-live="polite">
          <div className="section-heading">
            <div>
              <h3>
                匹配 {preview.matched_count} 个产物 · 待导入 {preview.new_count}{" "}
                个
              </h3>
              <p className="muted">
                已有 {preview.existing_count} 个，未匹配或不可导入{" "}
                {preview.skipped_count} 个。范围：所有已同步 Release。
              </p>
            </div>
            <Button
              className="primary"
              disabled={command.pending || !preview.new_count}
              onClick={() =>
                void command.run(
                  "release-batch-import",
                  (key) =>
                    write(
                      "/api/v1/apps/{id}/github/releases/import",
                      "post",
                      { rules, snapshot_token: preview.snapshot_token },
                      { id: appId, key },
                    ),
                  (value) => {
                    setTask(value);
                    setPreview(undefined);
                  },
                  "批量导入任务已创建。",
                )
              }
            >
              批量导入 {preview.new_count} 个安装包
            </Button>
          </div>
          <Table
            className="data-table"
            rowKey={(row) => `${row?.release_id}:${row?.asset_id}`}
            dataSource={preview.items}
            pagination={false}
            scroll={{ x: 620 }}
            empty="没有匹配的产物，请调整文件名或 Tag 规则。"
            columns={[
              { title: "安装包", dataIndex: "file_name" },
              { title: "Release Tag", dataIndex: "tag_name" },
              { title: "大小", dataIndex: "size_bytes", render: size },
              {
                title: "导入状态",
                dataIndex: "existing",
                render: (existing) => (existing ? "已有 · 自动跳过" : "待导入"),
              },
            ]}
          />
          {preview.truncated && (
            <p className="muted">
              仅展示前 200 个匹配产物；批量导入涵盖全部 {preview.new_count}{" "}
              个待导入产物。
            </p>
          )}
        </div>
      )}
      <div className="release-sync-status" aria-live="polite">
        <div>
          <strong>自动同步：{statusLabels[saved.status]}</strong>
          {saved.auto_enabled && (
            <span> · 每 {saved.interval_minutes} 分钟</span>
          )}
          {edited && <span className="muted"> · 表单修改尚未保存</span>}
        </div>
        {saved.next_check_at && <p>下次检查：{date(saved.next_check_at)}</p>}
        {result && (
          <p>
            最近导入：{date(result.checked_at)} · 新增 {result.created_count} 个
            · 已有 {result.existing_count} 个 · 失败 {result.failed_count} 个
          </p>
        )}
        {result?.errors.map((error, index) => (
          <p key={`${error.tag_name}:${index}`} className="field-error">
            {error.tag_name}：{error.error_code}
          </p>
        ))}
        {saved.last_task_id && (
          <Link to={`/admin/tasks/${saved.last_task_id}`}>
            查看最近同步任务
          </Link>
        )}
      </div>
    </Panel>
  );
}
