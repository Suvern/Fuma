import { RepositorySelect } from "../../shared/ui/RepositorySelect";
import { AppLifecycle } from "./AppLifecycle";
import { AppIcon, AppIconField } from "./AppIcon";
import { Statistics } from "./Statistics";
import { AppStorageBinding } from "./AppStorageBinding";
import { isGlobalAdmin } from "./permissions";
import Select from "@douyinfe/semi-ui-19/lib/es/select";
import {
  Button,
  Badge,
  CardLink,
  PageTabs,
  Panel,
  Disclosure,
} from "../../shared/ui/controls";
import { useEffect, useId, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Icon } from "../../shared/ui/Icon";
import { Dialog } from "../../shared/ui/Dialog";
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
  date,
  text,
  useCommand,
  useSession,
} from "../../shared/ui/common";

const platformNames = { android: "Android", ios: "iOS" } as const;
const modes = ["debug", "release"] as const;
type IdentifierDraft = Record<string, string>;

function identifierDraft(items: DTO<"AllowedPackageId">[]): IdentifierDraft {
  const result: IdentifierDraft = {};
  for (const platform of ["android", "ios"] as const) {
    for (const mode of modes) {
      result[`${platform}-${mode}`] = items
        .filter((item) => item.platform === platform && item.mode === mode)
        .map((item) => item.identifier)
        .join(", ");
    }
  }
  return result;
}

function identifierPayload(
  values: IdentifierDraft,
  platforms: DTO<"App">["platforms"],
): DTO<"AllowedPackageId">[] {
  return platforms.flatMap((platform) =>
    modes.flatMap((mode) =>
      (values[`${platform}-${mode}`] ?? "")
        .split(",")
        .map((identifier) => identifier.trim())
        .filter(Boolean)
        .map((identifier) => ({ platform, mode, identifier })),
    ),
  );
}

function PackageIdentifiers({
  platforms,
  values,
  onChange,
  disabled,
}: {
  platforms: DTO<"App">["platforms"];
  values: IdentifierDraft;
  onChange: (values: IdentifierDraft) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset className="package-identifiers" disabled={disabled}>
      <legend>允许的包标识</legend>
      <p className="muted">
        按平台分别配置 Debug 和 Release；多个标识用英文逗号分隔。
        可留空，待安装包解析入库前补齐。现有 GitHub Debug 下载不受此配置影响。
      </p>
      {platforms.map((platform) =>
        modes.map((mode) => {
          const key = `${platform}-${mode}`;
          const identifier =
            platform === "android"
              ? String.raw`[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+`
              : String.raw`[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*`;
          return (
            <Field
              key={key}
              name={`package_ids-${key}`}
              label={`${platformNames[platform]} ${mode === "debug" ? "Debug" : "Release"} ${platform === "android" ? "包名" : "Bundle ID"}`}
              value={values[key] ?? ""}
              onChange={(event) =>
                onChange({ ...values, [key]: event.target.value })
              }
              disabled={disabled}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              maxLength={20479}
              pattern={String.raw`\s*(?:${identifier}(?:\s*,\s*${identifier})*)?\s*`}
              validationMessage={
                platform === "android"
                  ? "请输入合法 Android 包名，例如 com.example.app；各段以字母开头，不支持通配符。"
                  : "Bundle ID 仅支持字母、数字、连字符和分隔点，不支持通配符。"
              }
              help={
                values[key]?.trim()
                  ? platform === "ios"
                    ? "比较时不区分大小写，保存原始拼写。"
                    : "包名区分大小写。"
                  : "待配置"
              }
            />
          );
        }),
      )}
    </fieldset>
  );
}

function Platforms({
  selected,
  onChange,
  disabled,
}: {
  selected: string[];
  onChange: (platforms: DTO<"App">["platforms"]) => void;
  disabled?: boolean;
}) {
  const input = useRef<HTMLFieldSetElement>(null);
  const helpId = useId();
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    input.current
      ?.querySelector("input")
      ?.setCustomValidity(selected.length ? "" : "请至少选择一个支持平台。");
  }, [selected.length]);
  return (
    <fieldset
      ref={input}
      onInvalid={() => setInvalid(true)}
      disabled={disabled}
      aria-describedby={helpId}
    >
      <legend>支持平台 *</legend>
      {(["android", "ios"] as const).map((platform) => (
        <Check
          key={platform}
          name="platforms"
          value={platform}
          label={platform === "android" ? "Android" : "iOS"}
          checked={selected.includes(platform)}
          disabled={disabled}
          aria-invalid={(invalid && !selected.length) || undefined}
          aria-describedby={helpId}
          onChange={(event) => {
            onChange(
              event.target.checked
                ? ([...selected, platform] as DTO<"App">["platforms"])
                : (selected.filter(
                    (value) => value !== platform,
                  ) as DTO<"App">["platforms"]),
            );
            setInvalid(false);
          }}
        />
      ))}
      <small
        id={helpId}
        role={invalid && !selected.length ? "alert" : undefined}
      >
        {invalid && !selected.length
          ? "请至少选择一个支持平台。"
          : "至少选择一个支持平台。"}
      </small>
      <small>HarmonyOS 待定，暂不支持。</small>
    </fieldset>
  );
}
export function AppsPage() {
  const session = useSession();
  const globalAdmin = isGlobalAdmin(session.data?.user);
  const [params, setParams] = useSearchParams();
  const creating = globalAdmin && params.get("new") === "1";
  const [saving, setSaving] = useState(false);
  function setCreating(open: boolean) {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (open) next.set("new", "1");
        else next.delete("new");
        return next;
      },
      { replace: true },
    );
  }
  const q = params.get("q") ?? "";
  const requestedPage = Number(params.get("page") ?? 1);
  const page =
    Number.isSafeInteger(requestedPage) && requestedPage > 0
      ? requestedPage
      : 1;
  const platformValue = params.get("platform");
  const platform =
    platformValue === "android" || platformValue === "ios"
      ? platformValue
      : undefined;
  const enabledValue = params.get("enabled");
  const enabled =
    enabledValue === "true"
      ? true
      : enabledValue === "false"
        ? false
        : undefined;
  const archivedValue = params.get("archived");
  const archived =
    archivedValue === "true"
      ? true
      : archivedValue === "false"
        ? false
        : undefined;
  const hasFilters = Boolean(
    q || platform || enabled !== undefined || archived !== undefined,
  );
  function filter(name: string, value: string) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(name, value);
      else next.delete(name);
      if (name !== "page") next.delete("page");
      return next;
    });
  }
  const query = useQuery({
    queryKey: ["apps", page, q, platform, enabled, archived],
    queryFn: ({ signal }) =>
      read("/api/v1/apps", {
        signal,
        query: { page, q, platform, enabled, archived },
      }),
  });
  return (
    <div className="apps-page">
      <Title
        description="连接应用与仓库，让每个版本都有归处。"
        actions={
          globalAdmin && (
            <Button className="primary" onClick={() => setCreating(true)}>
              <Icon name="plus" size={17} />
              新建应用
            </Button>
          )
        }
      >
        应用管理
      </Title>
      <Dialog
        open={creating}
        busy={saving}
        onClose={() => setCreating(false)}
        title="新建应用"
      >
        <CreateAppForm
          onClose={() => setCreating(false)}
          onPendingChange={setSaving}
        />
      </Dialog>
      <div className="app-filters">
        <form
          role="search"
          className="search"
          onSubmit={(event) => {
            event.preventDefault();
            filter("q", text(new FormData(event.currentTarget), "q"));
          }}
        >
          <Field
            key={q}
            name="q"
            label="关键词"
            type="search"
            defaultValue={q}
            maxLength={200}
            placeholder="搜索应用名称或包标识"
          />
          <Button>搜索</Button>
        </form>
        <div className="filter-field">
          <span id="apps-平台筛选">平台筛选</span>
          <Select
            aria-labelledby="apps-平台筛选"
            value={platform ?? ""}
            onChange={(value) => filter("platform", String(value ?? ""))}
            optionList={[
              { value: "", label: "全部平台" },
              { value: "android", label: "Android" },
              { value: "ios", label: "iOS" },
            ]}
          />
        </div>
        <div className="filter-field">
          <span id="apps-状态筛选">状态筛选</span>
          <Select
            aria-labelledby="apps-状态筛选"
            value={
              enabledValue === "true" || enabledValue === "false"
                ? enabledValue
                : ""
            }
            onChange={(value) => filter("enabled", String(value ?? ""))}
            optionList={[
              { value: "", label: "全部状态" },
              { value: "true", label: "已启用" },
              { value: "false", label: "已停用" },
            ]}
          />
        </div>
        <div className="filter-field">
          <span id="apps-归档筛选">归档筛选</span>
          <Select
            aria-labelledby="apps-归档筛选"
            value={archived === undefined ? "" : String(archived)}
            onChange={(value) => filter("archived", String(value ?? ""))}
            optionList={[
              { value: "", label: "全部归档状态" },
              { value: "false", label: "未归档" },
              { value: "true", label: "已归档" },
            ]}
          />
        </div>
      </div>
      <div className="apps-results-heading">
        <h2 className="collection-label">
          {hasFilters ? "筛选结果" : "全部应用"}
          {query.data && <Badge className="count">{query.data.total}</Badge>}
        </h2>
        {hasFilters && (
          <Button
            onClick={() =>
              setParams((current) => {
                const next = new URLSearchParams(current);
                for (const key of [
                  "q",
                  "platform",
                  "enabled",
                  "archived",
                  "page",
                ])
                  next.delete(key);
                return next;
              })
            }
          >
            清空筛选
          </Button>
        )}
      </div>
      <ErrorBox error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="card-grid apps-grid">
            {query.data?.items.map((app) => (
              <CardLink
                className="app-card apps-list-card"
                key={app.id}
                to={`/admin/apps/${app.id}`}
              >
                <div className="apps-card-heading">
                  <AppIcon name={app.name} value={app.icon_data} />
                  <div className="apps-card-identity">
                    <h3>{app.name}</h3>
                    <p>{app.description || "暂无描述"}</p>
                  </div>
                  <Badge
                    className={
                      !app.archived_at && app.enabled ? "pass" : "badge"
                    }
                  >
                    {app.archived_at
                      ? "已归档"
                      : app.enabled
                        ? "已启用"
                        : "已停用"}
                  </Badge>
                </div>
                <div className="inline apps-card-platforms">
                  {app.platforms.map((p) => (
                    <span key={p}>
                      <Status value={p} />
                      {app.disabled_platforms?.includes(p) && "（已停用）"}
                    </span>
                  ))}
                </div>
                <dl className="apps-card-stats">
                  <div>
                    <dt>安装包</dt>
                    <dd>{app.package_count ?? 0}</dd>
                  </div>
                  <div>
                    <dt>发布</dt>
                    <dd>{app.publication_count ?? 0}</dd>
                  </div>
                  <div>
                    <dt>旧版 Debug 包</dt>
                    <dd>{app.debug_entry_count}</dd>
                  </div>
                </dl>
                <div className="apps-card-footer">
                  <p className="apps-card-repository">
                    <Icon name="branch" size={14} />
                    <span>{app.repository?.full_name ?? "未绑定仓库"}</span>
                  </p>
                  <p>更新于 {date(app.updated_at)}</p>
                </div>
              </CardLink>
            ))}
          </div>
          {query.data && !query.data.items.length && (
            <Empty
              title={hasFilters ? "没有匹配的应用" : "添加你的第一个应用"}
              icon="apps"
              action={
                globalAdmin &&
                !hasFilters && (
                  <Button className="primary" onClick={() => setCreating(true)}>
                    <Icon name="plus" size={16} />
                    新建应用
                  </Button>
                )
              }
            >
              {hasFilters
                ? "试试其他名称、包标识或筛选条件。"
                : globalAdmin
                  ? "支持 Android 与 iOS。创建后配置 Debug/Release 存储桶，再接入 GitHub Actions 通知。"
                  : "尚未获得应用授权，请联系管理员分配应用。"}
            </Empty>
          )}
          <Pager
            data={query.data}
            page={page}
            setPage={(value) => filter("page", String(value))}
          />
        </>
      )}
    </div>
  );
}
function CreateAppForm({
  onClose,
  onPendingChange,
}: {
  onClose: () => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const cmd = useCommand();
  const navigate = useNavigate();
  useEffect(() => {
    onPendingChange(cmd.pending);
  }, [cmd.pending, onPendingChange]);
  const [platforms, setPlatforms] = useState<DTO<"App">["platforms"]>([
    "android",
  ]);
  const [iconData, setIconData] = useState("");
  const [identifiers, setIdentifiers] = useState<IdentifierDraft>(() =>
    identifierDraft([]),
  );
  return (
    <>
      <p className="muted">先添加基本信息，创建后配置 Debug/Release 存储桶，再接入 GitHub Actions 通知。</p>
      {cmd.feedback}
      <Form
        submit={(f) =>
          void cmd.run(
            JSON.stringify({
              fields: [...f],
              platforms,
              identifiers,
              iconData,
            }),
            (key) =>
              write(
                "/api/v1/apps",
                "post",
                {
                  name: text(f, "name"),
                  public_slug: text(f, "public_slug"),
                  description: text(f, "description"),
                  icon_data: iconData,
                  platforms,
                  allowed_package_ids: identifierPayload(
                    identifiers,
                    platforms,
                  ),
                },
                { key },
              ),
            (app) => navigate(`/admin/apps/${app.id}`),
          )
        }
      >
        <Field name="name" label="应用名称" required maxLength={100} />
        <Field
          name="public_slug"
          label="分发标识"
          required
          minLength={3}
          maxLength={64}
          pattern={String.raw`[a-z0-9][a-z0-9\-]*[a-z0-9]`}
          validationMessage="请输入 3–64 位小写字母、数字或连字符，首尾须为字母或数字。"
          help="小写字母、数字及连字符；创建后不可修改。"
        />
        <Field name="description" label="描述" maxLength={2000} />
        <AppIconField
          value={iconData}
          onChange={setIconData}
          disabled={cmd.pending}
        />
        <Platforms selected={platforms} onChange={setPlatforms} />
        <Disclosure title="包标识配置（可稍后补齐）">
          <PackageIdentifiers
            platforms={platforms}
            values={identifiers}
            onChange={setIdentifiers}
            disabled={cmd.pending}
          />
        </Disclosure>
        <div className="form-actions">
          <Button type="button" disabled={cmd.pending} onClick={onClose}>
            取消
          </Button>
          <Button className="primary" disabled={cmd.pending}>
            {cmd.pending ? "正在创建…" : "创建应用"}
          </Button>
        </div>
      </Form>
    </>
  );
}

function basicValues(app: DTO<"App">) {
  return {
    name: app.name,
    description: app.description ?? "",
    platforms: app.platforms,
    disabled_platforms: app.disabled_platforms ?? [],
    icon_data: app.icon_data ?? "",
    enabled: app.enabled,
    identifiers: identifierDraft(app.allowed_package_ids ?? []),
  };
}
export function AppPage() {
  const { id = "" } = useParams();
  const query = useQuery({
    queryKey: ["app", id],
    queryFn: () => read("/api/v1/apps/{id}", { id }),
  });
  if (query.isPending) return <Loading />;
  if (!query.data) return <ErrorBox error={query.error} />;
  return <AppEditor key={id} app={query.data} />;
}
function AppEditor({ app }: { app: DTO<"App"> }) {
  const session = useSession();
  const globalAdmin = isGlobalAdmin(session.data?.user);
  const cmd = useCommand();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
  const [draft, setDraft] = useState<{
    base: DTO<"App">;
    values: ReturnType<typeof basicValues>;
  } | null>(null);
  const values = draft?.values ?? basicValues(app);
  const locked = !editing || !!app.archived_at || cmd.pending;
  // Repository-only updates may advance the revision without invalidating this draft.
  // Keep the original revision if another editor changed any basic information.
  const revision =
    draft &&
    JSON.stringify(basicValues(draft.base)) !== JSON.stringify(basicValues(app))
      ? draft.base.revision
      : app.revision;
  function change(patch: Partial<ReturnType<typeof basicValues>>) {
    setDraft((current) => ({
      base: current?.base ?? app,
      values: { ...(current?.values ?? basicValues(app)), ...patch },
    }));
  }
  const navigate = useNavigate();
  return (
    <div className="app-settings-page">
      <Title description="维护基本信息，为 Debug/Release 分别绑定唯一包源存储桶，并接入 GitHub Actions 通知。">
        {app.name}
      </Title>
      <PageTabs className="tabs">
        <Link to={`/admin/apps/${app.id}/packages`}>安装包</Link>
        <Link to={`/admin/apps/${app.id}/versions`}>版本发布</Link>
        <Link to={`/admin/apps/${app.id}/debug`}>Debug 包</Link>
        <Link to={`/admin/apps/${app.id}/actions`}>Actions 规则</Link>
        <Link to={`/admin/apps/${app.id}/events`}>构建事件</Link>
        <Link to={`/admin/apps/${app.id}/notifications`}>飞书卡片</Link>
      </PageTabs>
      <div className="inline">
        <AppIcon name={app.name} value={app.icon_data} />
        <p>
          {app.package_count ?? 0} 个安装包 · {app.publication_count ?? 0} 个发布
        </p>
      </div>
      {cmd.feedback}
      <div className="two-columns">
        <Panel className="panel">
          <div className="settings-section-heading">
            <h2>基本信息</h2>
            {!editing && !app.archived_at && (
              <Button
                type="button"
                aria-label="修改基本信息"
                onClick={() => setEditing(true)}
              >
                修改
              </Button>
            )}
          </div>
          <p className="muted settings-edit-hint">
            {editing
              ? "修改后请保存，取消将恢复已保存的内容。"
              : "已保存，点击「修改」后编辑。"}
          </p>
          <fieldset
            disabled={!!app.archived_at}
            style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
          >
            <Form
              key={editing ? "editing" : "saved"}
              submit={(f) =>
                !locked &&
                void cmd.run(
                  "app-update",
                  () =>
                    write(
                      "/api/v1/apps/{id}",
                      "patch",
                      {
                        name: text(f, "name"),
                        description: text(f, "description"),
                        icon_data: values.icon_data,
                        disabled_platforms: values.disabled_platforms.filter(
                          (p) => values.platforms.includes(p),
                        ),
                        platforms: values.platforms,
                        enabled: values.enabled,
                        allowed_package_ids: identifierPayload(
                          values.identifiers,
                          values.platforms,
                        ),
                      },
                      { id: app.id, revision },
                    ),
                  (saved) => {
                    client.setQueryData(["app", app.id], saved);
                    setDraft(null);
                    setEditing(false);
                  },
                  "基本信息已保存。",
                  JSON.stringify(values.disabled_platforms) !==
                    JSON.stringify(app.disabled_platforms ?? [])
                    ? "更改平台启停状态？停用将停止该平台的新上传、发布和下载授权，保留历史记录及已签发的短期链接；重新启用会恢复仍处于已发布状态的私有版本可见。公开发布需先下架并完成访问收回。"
                    : undefined,
                )
              }
            >
              <div className="settings-identity-fields">
                <Field
                  name="name"
                  label="名称"
                  value={values.name}
                  onChange={(event) => change({ name: event.target.value })}
                  disabled={locked}
                  required
                  maxLength={100}
                />
                <Field
                  name="public_slug"
                  label="分发标识"
                  value={app.public_slug}
                  readOnly
                  disabled
                />
              </div>
              <Field
                name="description"
                label="描述"
                value={values.description}
                onChange={(event) =>
                  change({ description: event.target.value })
                }
                disabled={locked}
                maxLength={2000}
              />
              {!editing && (
                <div className="settings-basic-summary">
                  <span>
                    {values.platforms.map((p) => platformNames[p]).join(" · ")}
                  </span>
                  <Badge>{values.enabled ? "已启用" : "已停用"}</Badge>
                </div>
              )}
              <div className="settings-basic-details">
                {editing ? (
                  <h3>图标、平台与包标识</h3>
                ) : (
                  <Button
                    type="button"
                    className="settings-details-toggle"
                    aria-expanded={detailsOpen}
                    aria-controls={detailsId}
                    onClick={() => setDetailsOpen(!detailsOpen)}
                  >
                    <span>图标、平台与包标识</span>
                    <span aria-hidden="true">{detailsOpen ? "−" : "+"}</span>
                  </Button>
                )}
                <div id={detailsId} hidden={!editing && !detailsOpen}>
                  <div className="settings-details-fields">
                    <Platforms
                      selected={values.platforms}
                      onChange={(platforms) => change({ platforms })}
                      disabled={locked}
                    />
                    <AppIconField
                      value={values.icon_data}
                      onChange={(icon_data) => change({ icon_data })}
                      disabled={locked}
                    />
                    <fieldset disabled={locked}>
                      <legend>平台运行状态</legend>
                      <p className="muted">
                        停用保留平台配置及历史。再次启用会恢复已发布私有版本的可见性；公开发布须先下架并完成访问收回。
                      </p>
                      {values.platforms.map((p) => (
                        <Check
                          key={p}
                          name={`platform-enabled-${p}`}
                          label={`启用 ${platformNames[p]} 平台`}
                          checked={!values.disabled_platforms.includes(p)}
                          disabled={locked}
                          onChange={(event) =>
                            change({
                              disabled_platforms: event.target.checked
                                ? values.disabled_platforms.filter(
                                    (item) => item !== p,
                                  )
                                : [...values.disabled_platforms, p],
                            })
                          }
                        />
                      ))}
                    </fieldset>
                    <Check
                      name="enabled"
                      label="启用 App"
                      checked={values.enabled}
                      onChange={(event) =>
                        change({ enabled: event.target.checked })
                      }
                      disabled={locked}
                    />
                    <PackageIdentifiers
                      platforms={values.platforms}
                      values={values.identifiers}
                      onChange={(identifiers) => change({ identifiers })}
                      disabled={locked}
                    />
                  </div>
                </div>
              </div>
              {editing && (
                <div className="form-actions">
                  <Button
                    type="button"
                    disabled={cmd.pending}
                    onClick={() => {
                      setDraft(null);
                      setEditing(false);
                    }}
                  >
                    取消修改
                  </Button>
                  <Button disabled={cmd.pending} className="primary">
                    保存
                  </Button>
                </div>
              )}
            </Form>
          </fieldset>
        </Panel>
        {!app.archived_at &&
          (globalAdmin ? (
            <RepositoryBinding app={app} />
          ) : (
            <Panel>
              <h2>仓库绑定</h2>
              <p>{app.repository?.full_name ?? "尚未绑定仓库"}</p>
              <p className="muted">
                仓库凭据与绑定由管理员管理。已有绑定可用于此应用的 Release
                导入。
              </p>
            </Panel>
          ))}
      </div>
      {!app.archived_at && <AppStorageBinding appId={app.id} />}
      <Disclosure title="分发统计">
        <Statistics appId={app.id} />
      </Disclosure>
      <AppLifecycle app={app} />
      {globalAdmin && (
        <Panel className="danger-zone">
          <h2>删除应用</h2>
          <p className="muted">删除后下载入口将不可用，历史记录保留。</p>{" "}
          {globalAdmin && (
            <Button
              className="danger"
              disabled={cmd.pending}
              onClick={() =>
                void cmd.run(
                  "app-delete",
                  () =>
                    write("/api/v1/apps/{id}", "delete", undefined, {
                      id: app.id,
                      revision: app.revision,
                    }),
                  () => navigate("/admin/apps"),
                  undefined,
                  `删除 App「${app.name}」？历史记录将保留，下载入口将不可用。`,
                )
              }
            >
              删除 App
            </Button>
          )}
        </Panel>
      )}
    </div>
  );
}
function RepositoryBinding({ app }: { app: DTO<"App"> }) {
  const [editing, setEditing] = useState(!app.repository);
  const [revision, setRevision] = useState(app.revision);
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const connectors = useQuery({
    queryKey: ["connectors-select", page, search],
    queryFn: ({ signal }) =>
      read("/api/v1/connectors/github", { query: { page, q: search }, signal }),
  });
  const [connectorId, setConnectorId] = useState(
    app.repository?.connector_id ?? "",
  );
  const [repoName, setRepoName] = useState(app.repository?.full_name ?? "");
  const cmd = useCommand();
  const locked = !editing || cmd.pending;
  const currentConnectorId = editing
    ? connectorId
    : (app.repository?.connector_id ?? "");
  const currentRepoName = editing
    ? repoName
    : (app.repository?.full_name ?? "");
  const options =
    connectors.data?.items.map((c) => ({
      value: c.id,
      label: c.name,
      disabled: !c.enabled,
    })) ?? [];
  if (
    currentConnectorId &&
    !options.some((c) => c.value === currentConnectorId)
  ) {
    options.unshift({
      value: currentConnectorId,
      label: "已保存的 GitHub 连接",
      disabled: false,
    });
  }
  return (
    <Panel>
      <div className="settings-section-heading">
        <h2>GitHub Actions 来源（仅通知）</h2>
        {!editing && (
          <Button
            type="button"
            aria-label="修改仓库绑定"
            onClick={() => {
              setConnectorId(app.repository?.connector_id ?? "");
              setRepoName(app.repository?.full_name ?? "");
              setRevision(app.revision);
              setSearch("");
              setPage(1);
              setEditing(true);
            }}
          >
            修改
          </Button>
        )}
      </div>
      <p className="muted settings-edit-hint">
        {editing
          ? "选择连接与仓库，保存前会验证读取权限；这里只用于校验 workflow 来源，不读取 GitHub Release。"
          : "已绑定，仅用于校验 GitHub Actions workflow 来源；点击「修改」后更换连接或仓库。"}
      </p>
      {cmd.feedback}
      <div className="field">
        <span id="connector-label">GitHub 连接</span>
        <Select
          aria-labelledby="connector-label"
          aria-label="GitHub 连接"
          value={currentConnectorId || undefined}
          placeholder="搜索并选择连接"
          filter
          remote
          loading={connectors.isFetching}
          disabled={locked}
          onSearch={(value) => {
            setSearch(value);
            setPage(1);
          }}
          onChange={(value) => {
            setConnectorId(String(value ?? ""));
            setRepoName("");
          }}
          optionList={options}
          outerBottomSlot={
            connectors.data &&
            connectors.data.total > connectors.data.page_size ? (
              <Pager data={connectors.data} page={page} setPage={setPage} />
            ) : undefined
          }
          style={{ width: "100%" }}
        />
      </div>
      <ErrorBox error={connectors.error} />
      <Form
        submit={() => {
          if (locked || !connectorId || !repoName.trim()) return;
          void cmd.run(
            "bind-repository",
            () =>
              write(
                "/api/v1/apps/{id}/repository",
                "put",
                { connector_id: connectorId, full_name: repoName.trim() },
                { id: app.id, revision },
              ),
            (saved) => {
              client.setQueryData(["app", app.id], saved);
              setEditing(false);
            },
            "仓库绑定已保存。",
          );
        }}
      >
        <RepositorySelect
          key={`${currentConnectorId}-${editing}`}
          connectorId={currentConnectorId}
          value={currentRepoName}
          onChange={setRepoName}
          disabled={locked}
        />
        {editing && (
          <Disclosure title="手动填写仓库名称">
            <Field
              label="仓库完整名称"
              name="full_name"
              value={repoName}
              onChange={(event) => setRepoName(event.target.value)}
              disabled={cmd.pending || !connectorId}
              pattern={String.raw`[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+`}
              validationMessage="请按 owner/repository 格式填写仓库完整名称。"
              help="未在搜索中找到时，可填写已知仓库；服务端会验证读取权限。"
            />
          </Disclosure>
        )}
        {editing && (
          <div className="form-actions">
            {app.repository && (
              <Button
                type="button"
                disabled={cmd.pending}
                onClick={() => setEditing(false)}
              >
                取消修改
              </Button>
            )}
            <Button
              className="primary"
              loading={cmd.pending}
              disabled={cmd.pending || !connectorId || !repoName.trim()}
            >
              验证并绑定
            </Button>
          </div>
        )}
      </Form>
      <Link to="/admin/connectors">管理 GitHub 连接</Link>
    </Panel>
  );
}
