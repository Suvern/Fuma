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
      query.state.data?.sync_state === "syncing" ? 2500 : false,
  });
  const cmd = useCommand();
  return (
    <>
      <Title description="检索仓库的 Release，选择 APK 或 IPA 作为 Debug 分发条目。">
        Release 安装包
      </Title>
      <PageTabs />
      <div className="toolbar">
        {filters.search}
        <label>
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
        </label>
        <label>
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
    <Panel className="panel">
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
        <Table
          className="data-table"
          rowKey="id"
          pagination={false}
          dataSource={r.assets}
          empty={<Empty>此 Release 暂无附件。</Empty>}
          scroll={{ x: 620 }}
          rowSelection={{
            selectedRowKeys: selected,
            onChange: (keys) => setSelected((keys ?? []).map(String)),
            getCheckboxProps: (asset) => ({
              disabled:
                r.draft ||
                !asset.supported ||
                !asset.platform ||
                !!asset.debug_entry_id,
              "aria-label": `选择 ${asset.name}`,
            }),
          }}
          columns={[
            { title: "安装包", dataIndex: "name", width: 280 },
            {
              title: "平台",
              dataIndex: "platform",
              render: (platform) =>
                platform ? <Status value={platform} /> : "不支持",
            },
            { title: "大小", dataIndex: "size_bytes", render: size },
            {
              title: "状态",
              render: (_, asset) =>
                asset.debug_entry_id ? (
                  <Link to={`/admin/debug/${asset.debug_entry_id}`}>
                    已导入
                  </Link>
                ) : (
                  <Status value={asset.cache_state} />
                ),
            },
          ]}
        />
        <div className="inline-form">
          <Field
            name="version_name"
            label="版本号（可选）"
            maxLength={100}
            help="未填写时仅显示来源 Tag。"
          />
          <Field name="build_number" label="构建号（可选）" maxLength={100} />
        </div>
        <Button className="primary" disabled={cmd.pending || !selected.length}>
          导入 {selected.length || ""} 个 Debug 包
        </Button>
      </Form>
    </Panel>
  );
}
