import { Select as FormSelect } from "../../shared/ui/FormControls";
import Select from "@douyinfe/semi-ui-19/lib/es/select";
import Table from "@douyinfe/semi-ui-19/lib/es/table";
import {
  Input,
  PageTabs,
  Button,
  Panel,
  Badge,
  Disclosure,
} from "../../shared/ui/controls";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { GitHubPackageImport } from "../library/GitHubImport";
import { ReleaseRules } from "./ReleaseRules";
import {
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
export { ConnectorsPage } from "./Connectors";
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
      query.state.data?.sync_state === "syncing" ? 2500 : 30_000,
  });
  const cmd = useCommand();
  return (
    <div className="app-tab-page github-releases-page">
      <Title description="按文件名规则批量导入安装包，自动检查后续 Release 更新。">
        Release 安装包
      </Title>
      <PageTabs />
      <ReleaseRules
        key={id}
        appId={id}
        snapshotReady={Boolean(q.data?.synced_at)}
      />
      <div className="app-tab-filters release-filters">
        {filters.search}
        <div className="field">
          <span id="release-filter-label">预发布</span>
          <Select
            aria-labelledby="release-filter-label"
            style={{ minWidth: 160 }}
            value={prerelease}
            onChange={(value) => {
              setPrerelease(String(value ?? ""));
              filters.setPage(1);
            }}
          >
            <Select.Option value="all">全部</Select.Option>
            <Select.Option value="only">仅预发布</Select.Option>
            <Select.Option value="exclude">排除预发布</Select.Option>
          </Select>
        </div>
        <label className="field">
          文件名筛选
          <Input
            value={assetName}
            onChange={(e) => {
              setAssetName(e.target.value);
              filters.setPage(1);
            }}
          />
        </label>
        <Button
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
        </Button>
      </div>
      {cmd.feedback}
      <TaskNotice task={task} />
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.data && (
        <div className="muted">
          同步状态：
          <Status value={q.data.sync_state} /> · {date(q.data.synced_at)}{" "}
          {q.data.sync_error_code}
        </div>
      )}
      {q.data?.items.map((release) => (
        <ReleaseCard key={release.id} appId={id} release={release} />
      ))}
      {q.data && !q.data.items.length && (
        <Empty>未找到 Release，请检查搜索条件或发起同步。</Empty>
      )}
      <Pager data={q.data} {...filters} />
    </div>
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
  const [importOpen, setImportOpen] = useState(false);
  const [target, setTarget] = useState("library");
  const legacySelected = selected.filter(
    (id) => !r.assets.find((asset) => asset.id === id)?.debug_entry_id,
  );
  return (
    <Panel className="panel release-card">
      <div className="section-heading">
        <h2>{r.name || r.tag_name}</h2>
        <div className="inline">
          <Badge className="badge">Tag {r.tag_name}</Badge>
          {r.draft && <Badge className="badge">草稿 · 不可分发</Badge>}
          {r.prerelease && <Badge className="badge">预发布</Badge>}
        </div>
      </div>
      <p className="muted">{date(r.published_at)}</p>
      <Disclosure title={<>发布说明</>}>
        <p className="release-notes">{r.body || "暂无说明"}</p>
      </Disclosure>
      {cmd.feedback}
      <Table
        className="data-table"
        rowKey="id"
        pagination={false}
        dataSource={r.assets}
        empty={<Empty>此 Release 暂无附件。</Empty>}
        scroll={{ x: 760 }}
        rowSelection={{
          selectedRowKeys: selected,
          onChange: (keys) => setSelected((keys ?? []).map(String)),
          getCheckboxProps: (asset) => ({
            disabled: r.draft || !asset.supported || !asset.platform,
            "aria-label": `选择 ${asset.name}`,
          }),
        }}
        columns={[
          {
            title: "安装包",
            dataIndex: "name",
            width: 280,
            render: (name: string) => (
              <span className="wrap-token">{name}</span>
            ),
          },
          {
            title: "平台",
            dataIndex: "platform",
            width: 90,
            render: (platform) =>
              platform ? <Status value={platform} /> : "不支持",
          },
          { title: "大小", dataIndex: "size_bytes", width: 100, render: size },
          {
            title: "状态",
            width: 200,
            render: (_, asset) =>
              asset.debug_entry_id ? (
                <Link to={`/admin/debug/${asset.debug_entry_id}`}>
                  已在旧版 Debug 分发 · 查看
                </Link>
              ) : (
                <Status value={asset.cache_state} />
              ),
          },
        ]}
      />
      <Button
        type="button"
        className="primary"
        disabled={!importOpen && (!selected.length || r.draft)}
        aria-expanded={importOpen}
        aria-controls={`release-import-${r.id}`}
        onClick={() => setImportOpen(!importOpen)}
      >
        {importOpen
          ? "收起导入设置"
          : selected.length
            ? `导入所选 ${selected.length} 个附件`
            : "请先选择附件"}
      </Button>
      {importOpen && (
        <div id={`release-import-${r.id}`} className="release-import-settings">
          <div className="field">
            <FormSelect
              label="导入目标"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="library">安装包库（解析、持久保存）</option>
              <option value="legacy">旧版 Debug 分发（兼容缓存流程）</option>
            </FormSelect>
          </div>
          {target === "library" ? (
            <GitHubPackageImport
              appId={appId}
              release={r}
              selected={selected}
            />
          ) : (
            <>
              <p>
                旧版流程创建 Debug
                下载条目并按需缓存，不解析包标识、不加入安装包库、不创建版本发布，也不发送通知。已导入的附件会跳过。
              </p>
              {legacySelected.length !== selected.length && (
                <p role="status">
                  部分附件已在旧版 Debug
                  分发中，请使用表格中的查看入口；无需再次导入。
                </p>
              )}
              <Form
                submit={(f) =>
                  void cmd.run(
                    JSON.stringify([r.id, legacySelected, ...f]),
                    (key) =>
                      write(
                        "/api/v1/apps/{id}/debug-entries",
                        "post",
                        {
                          release_id: r.id,
                          enabled: true,
                          assets: legacySelected.map((asset_id) => ({
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
                <div className="inline-form">
                  <Field
                    name="version_name"
                    label="版本号（可选）"
                    maxLength={100}
                    help="未填写时仅显示来源 Tag。"
                  />
                  <Field
                    name="build_number"
                    label="构建号（可选）"
                    maxLength={100}
                  />
                </div>
                <Button
                  className="primary"
                  disabled={cmd.pending || !legacySelected.length}
                >
                  导入 {legacySelected.length || ""} 个到旧版 Debug 分发
                </Button>
              </Form>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}
