import { Select } from "../../shared/ui/FormControls";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { Button, Notice, Panel } from "../../shared/ui/controls";
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
import { isGlobalAdmin } from "../m1/permissions";

const statuses: Record<string, string> = {
  unverified: "待验证",
  testing: "测试中",
  ready: "可用",
  failed: "测试失败",
};

export function StoragePage() {
  const filters = useFilters("搜索存储名称或桶名…");
  const cmd = useCommand();
  const [provider, setProvider] = useState<"cos" | "oss">("cos");
  const [credentialId, setCredentialId] = useState("");
  const credentialMode = credentialId ? "existing" : "new";
  const [formKey, setFormKey] = useState(0);
  const credentials = useQuery({
    queryKey: ["storage-credentials"],
    queryFn: () =>
      read("/api/v1/settings/storage-credentials", {
        query: { page: 1, page_size: 100 },
      }),
    staleTime: 15_000,
  });
  const query = useQuery({
    queryKey: ["storage", filters.page, filters.q],
    queryFn: () =>
      read("/api/v1/settings/storage-locations", {
        query: { page: filters.page, q: filters.q },
      }),
    refetchInterval: 5000,
  });
  return (
    <>
      <Title description="登记并验证可用的 COS / OSS 存储桶。包来源必须在应用设置中按 App 分别绑定 Debug 或 Release；此页不决定任何 App 的分发来源。">
        存储桶资源池
      </Title>
      <Notice>
        <p>
          这里管理可复用的桶连接、凭据与健康状态；真正的包来源由每个 App 的 Debug / Release
          绑定决定。连接测试会在桶根目录或配置的前缀下写入、回读并删除小文件，需要对象读写、删除及桶版本配置读取权限。
        </p>
        <p>
          新增或验证存储桶后，请前往 <Link to="/admin/apps">应用管理</Link> 为具体 App
          分别绑定两个 channel；不要把全局资源池当作默认分发入口。
        </p>
      </Notice>
      {cmd.feedback}
      <Panel>
        <details>
          <summary>新增 COS / OSS 存储桶资源</summary>
          <Form
            key={formKey}
            submit={(form) =>
              void cmd.run(
                "storage-create",
                () =>
                  write("/api/v1/settings/storage-locations", "post", {
                    name: text(form, "name"),
                    provider,
                    region: text(form, "region"),
                    bucket: text(form, "bucket"),
                    prefix: text(form, "prefix"),
                    read_mode: text(form, "read_mode") as "private" | "public",
                    credential_id:
                      credentialMode === "existing"
                        ? text(form, "credential_id") || undefined
                        : undefined,
                    credential_name:
                      credentialMode === "new"
                        ? text(form, "credential_name") || undefined
                        : undefined,
                    access_key_id:
                      credentialMode === "new"
                        ? text(form, "access_key_id")
                        : undefined,
                    access_key_secret:
                      credentialMode === "new"
                        ? text(form, "access_key_secret")
                        : undefined,
                  }),
                () => {
                  setFormKey((k) => k + 1);
                  void credentials.refetch();
                },
                "配置已保存，请运行连接测试。",
              )
            }
          >
            <Field name="name" label="配置名称" required maxLength={100} />
            <div className="field">
              <Select
                label="云厂商"
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value as "cos" | "oss");
                  setCredentialId("");
                }}
              >
                <option value="cos">腾讯云 COS</option>
                <option value="oss">阿里云 OSS</option>
              </Select>
            </div>
            <Field
              name="region"
              label="地域标识"
              placeholder={provider === "cos" ? "ap-guangzhou" : "cn-hangzhou"}
              required
            />
            <Field
              name="bucket"
              label={provider === "cos" ? "桶名称（含 APPID 后缀）" : "桶名称"}
              required
            />
            <Field
              name="prefix"
              label="Fuma 资源池路径前缀（可选）"
              placeholder="留空表示桶根目录，如 android/ios"
            />
            <div className="field">
              <Select label="读取模式" name="read_mode">
                <option value="private">私有原件（Debug / Release 均可）</option>
                <option value="public">公开副本（仅 Release 可绑定）</option>
              </Select>
            </div>
            <div className="field">
              <Select
                label="访问凭据"
                name="credential_id"
                value={credentialId}
                onChange={(e) => setCredentialId(e.target.value)}
              >
                <option value="">新建凭据档案（只需填写一次）</option>
                {credentials.data?.items
                  .filter((item) => item.provider === provider && item.enabled)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      使用已有：{item.name} · {item.access_key_hint}（已绑定 {item.location_count} 个桶）
                    </option>
                  ))}
              </Select>
            </div>
            {credentialMode === "existing" ? (
              <p className="muted">
                该桶会复用选中的凭据；凭据只在服务端加密保存，不会回显 Secret。
              </p>
            ) : (
              <>
                <Field
                  name="credential_name"
                  label="凭据档案名称"
                  placeholder="例如：Joice COS 发布凭据"
                  required
                />
                <Field
                  name="access_key_id"
                  label={provider === "cos" ? "SecretId" : "AccessKey ID"}
                  type="password"
                  autoComplete="new-password"
                  required
                />
                <Field
                  name="access_key_secret"
                  label={provider === "cos" ? "SecretKey" : "AccessKey Secret"}
                  type="password"
                  autoComplete="new-password"
                  required
                />
              </>
            )}
            <p>
              前缀留空时直接管理桶根目录；例如根目录下的 <code>android/</code> 和 <code>ios/</code>。
              桶与路径身份固定；更换位置请新增配置，之后再到 App 设置绑定对应 channel。
            </p>
            <Button disabled={cmd.pending} className="primary">
              保存配置
            </Button>
          </Form>
        </details>
      </Panel>
      {filters.search}
      <ErrorBox error={query.error} />
      {query.isPending && <Loading />}
      {query.data?.items.length === 0 && (
        <Empty>
          暂无存储桶资源。请先新增并通过连接测试，再到应用设置按 Debug / Release 绑定。
        </Empty>
      )}
      {query.data?.items.map((row) => (
        <StorageCard key={row.id} row={row} />
      ))}
      <Pager data={query.data} {...filters} />
    </>
  );
}

function StorageCard({ row }: { row: DTO<"StorageInfo"> }) {
  const cmd = useCommand();
  const [formKey, setFormKey] = useState(0);
  const action = (
    name: "test" | "make-default" | "enable" | "disable",
    label: string,
  ) =>
    void cmd.run(
      `storage-${name}`,
      () =>
        write(
          `/api/v1/settings/storage-locations/{id}/${name}`,
          "post",
          undefined,
          { id: row.id, revision: row.revision },
        ),
      undefined,
      `${label}请求已完成。`,
      name === "disable"
        ? "停用后不再接收新文件，已有文件仍可读取。确认停用？"
        : undefined,
    );
  return (
    <Panel>
      <h2>
        {row.name}
      </h2>
      <p>
        {row.provider.toUpperCase()} · {row.region} · {row.bucket}/
        {row.prefix || "（桶根目录）"}
      </p>
      <p>
        访问凭据：{row.credential_name || "旧版桶专属凭据"}
      </p>
      <p>
        {row.read_mode === "private" ? "私有原件" : "公开副本"} ·{" "}
        {row.enabled ? statuses[row.status] : "已停用"} · 最近检查{" "}
        {date(row.checked_at)}
      </p>
      <p>
        记录内对象 {row.object_count} 个，合计{" "}
        {(row.managed_bytes / 1024 ** 2).toFixed(2)}{" "}
        MiB（含待清理对象，并非云账单）。
      </p>
      {row.error_message && <p role="alert">{row.error_message}</p>}
      {!!Object.keys(row.capabilities).length && (
        <dl>
          {Object.entries(row.capabilities).map(([key, value]) => (
            <div key={key}>
              <dt>
                {{
                  write: "写入",
                  read: "签名回读",
                  anonymous: "匿名读取",
                  cleanup: "测试对象清理",
                }[key] || key}
              </dt>
              <dd>
                {value === "passed"
                  ? "通过"
                  : value === "denied"
                    ? "已拒绝"
                    : value === "readable"
                      ? "可读取"
                      : value}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {row.task_id && (
        <Link to={`/admin/tasks/${row.task_id}`}>查看连接测试任务</Link>
      )}
      {cmd.feedback}
      <div className="toolbar">
        <Button
          disabled={cmd.pending || row.status === "testing"}
          onClick={() => action("test", "连接测试")}
        >
          连接测试
        </Button>
        <Button
          disabled={cmd.pending || row.status === "testing"}
          onClick={() =>
            action(
              row.enabled ? "disable" : "enable",
              row.enabled ? "停用" : "启用",
            )
          }
        >
          {row.enabled ? "停用" : "启用"}
        </Button>
      </div>
      <details>
        <summary>轮换凭据</summary>
        <p>候选凭据通过完整连接测试后才替换；失败保留原凭据供历史文件读取。</p>
        <Form
          key={formKey}
          submit={(form) =>
            void cmd.run(
              "rotate",
              () =>
                write(
                  "/api/v1/settings/storage-locations/{id}/credentials",
                  "put",
                  {
                    access_key_id: text(form, "access_key_id"),
                    access_key_secret: text(form, "access_key_secret"),
                  },
                  { id: row.id, revision: row.revision },
                ),
              () => setFormKey((k) => k + 1),
              "候选凭据已提交测试。",
            )
          }
        >
          <Field
            name="access_key_id"
            label="新访问标识"
            type="password"
            autoComplete="new-password"
            required
          />
          <Field
            name="access_key_secret"
            label="新访问密钥"
            type="password"
            autoComplete="new-password"
            required
          />
          <Button disabled={cmd.pending || row.status === "testing"}>
            验证并轮换
          </Button>
        </Form>
      </details>
    </Panel>
  );
}

export function StorageChoice({
  appId,
  mode,
  appChannel,
  value,
  onChange,
  disabled,
  cloudOnly = false,
  onAvailability,
}: {
  appId: string;
  mode: "private" | "public";
  /** When set, the package uploader is locked to the App channel binding. */
  appChannel?: "debug" | "release";
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  cloudOnly?: boolean;
  onAvailability?: (ids: string[]) => void;
}) {
  const session = useSession();
  const query = useQuery({
    queryKey: ["storage-choice", appId, session.data?.viewer_key],
    queryFn: () => read("/api/v1/apps/{id}/available-storage", { id: appId }),
  });
  const binding = useQuery({
    queryKey: ["app-package-storage", appId],
    queryFn: () => read("/api/v1/apps/{id}/package-storage", { id: appId }),
    enabled: Boolean(appChannel),
  });
  const boundChannel = appChannel ? binding.data?.[appChannel] : undefined;
  useEffect(() => {
    if (appChannel && boundChannel?.storage_location_id && value !== boundChannel.storage_location_id) {
      onChange(boundChannel.storage_location_id);
    }
  }, [appChannel, boundChannel?.storage_location_id, onChange, value]);
  useEffect(() => {
    onAvailability?.(
      query.data?.items
        .filter((row) => row.read_mode === mode)
        .map((row) => row.id) ?? [],
    );
  }, [query.data, mode, onAvailability]);
  return (
    <div>
      {appChannel ? (
        <>
          <p className="muted">
            {appChannel === "debug" ? "Debug" : "Release"} 包源存储桶：{" "}
            {boundChannel
              ? `${boundChannel.storage.name} / ${boundChannel.object_prefix || "桶根目录"}`
              : "尚未绑定，请先在应用设置中配置独立 COS 存储桶。"}
          </p>
          {!boundChannel && (
            <Link to={`/admin/apps/${appId}`}>
              配置 {appChannel === "debug" ? "Debug" : "Release"} 存储桶
            </Link>
          )}
          <ErrorBox error={binding.error} />
        </>
      ) : (
      <div className="field">
        <Select
          label={mode === "private" ? "原件存储位置" : "发布访问方式"}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          {cloudOnly ? (
            <option value="" disabled>
              请选择可用私有云存储
            </option>
          ) : mode === "private" ? (
            <>
              <option value="default">使用系统默认（未设置时存入本机）</option>
              <option value="">本机私有存储</option>
            </>
          ) : (
            <option value="">仅已验证的飞书租户成员</option>
          )}
          {query.data?.items
            .filter((row) => row.read_mode === mode)
            .map((row) => (
              <option key={row.id} value={row.id}>
                {row.name} ·{" "}
                {mode === "public"
                  ? "任何人可下载"
                  : row.provider.toUpperCase()}
              </option>
            ))}
        </Select>
      </div>
      )}
      <ErrorBox error={query.error} />
      {cloudOnly && query.isPending && (
        <p role="status">正在检查可用私有云存储…</p>
      )}
      {cloudOnly &&
        query.data &&
        !query.data.items.some((row) => row.read_mode === "private") && (
          <p role="status">
            尚无可用私有云存储。请先配置私有 COS /
            OSS，并通过连接测试；本机存储不支持旧版条目迁移。
          </p>
        )}
      {cloudOnly && (
        <Button
          type="button"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          重新检查存储
        </Button>
      )}
      {isGlobalAdmin(session.data?.user) ? (
        <Link to="/admin/settings/storage">配置或测试云存储</Link>
      ) : (
        <p className="muted">
          仅列出管理员已验证的可用存储，配置和凭据由管理员管理。
        </p>
      )}
    </div>
  );
}
