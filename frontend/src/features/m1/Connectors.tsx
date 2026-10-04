import { TextArea } from "../../shared/ui/FormControls";
import {
  Disclosure,
  Badge,
  Button,
  Notice,
  Input,
  Panel,
} from "../../shared/ui/controls";
import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { read, write, type DTO } from "../../shared/api/http";
import {
  Check,
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
} from "../../shared/ui/common";
import { Dialog } from "../../shared/ui/Dialog";
import { Icon } from "../../shared/ui/Icon";

const tokenSettings = "https://github.com/settings/personal-access-tokens";
const checkNames: Record<string, string> = {
  identity: "身份验证",
  repository: "仓库访问",
  contents: "Release 列表",
  assets: "安装包附件",
  actions: "Actions 构建记录",
};
const checkDescriptions: Record<string, string> = {
  identity: "验证令牌与 GitHub 账号",
  repository: "确认目标仓库在授权范围内",
  contents: "Contents · Read-only",
  assets: "Contents · Read-only",
  actions: "Actions · Read-only",
};

function PermissionGuide() {
  return (
    <Disclosure
      title={<>如何配置 GitHub 令牌权限？</>}
      className="connector-guide"
    >
      <ol>
        <li>在 GitHub 创建或编辑 Fine-grained personal access token。</li>
        <li>
          Resource owner 选择仓库所属账号或组织，Repository access
          选中要分发的仓库。
        </li>
        <li>
          Repository permissions 中将 <strong>Contents</strong> 设为{" "}
          <strong>Read-only</strong>；需要读取构建记录时，同时开启{" "}
          <strong>Actions · Read-only</strong>。
        </li>
      </ol>
      <p>
        组织仓库可能需要管理员审批。使用 Classic PAT 访问私有仓库时需 repo
        scope，组织启用 SSO 时还需完成 SSO 授权。
      </p>
      <a href={tokenSettings} target="_blank" rel="noreferrer">
        打开 GitHub 令牌设置 <Icon name="external" size={14} />
      </a>
    </Disclosure>
  );
}

export function ConnectorsPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const q = useQuery({
    queryKey: ["connectors", page, query],
    queryFn: () =>
      read("/api/v1/connectors/github", { query: { page, q: query } }),
  });
  return (
    <div className="connectors-page">
      <Title
        description="连接代码与交付，确认 Fuma 能读取仓库、Release 和安装包。"
        actions={
          <Button className="primary" onClick={() => setCreating(true)}>
            <Icon name="plus" size={17} />
            新建连接
          </Button>
        }
      >
        GitHub 连接
      </Title>
      {notice && (
        <Notice role="status" className="notice success">
          {notice}
        </Notice>
      )}
      <div className="connector-list-toolbar">
        <p className="muted">
          {q.data ? `${q.data.total} 个连接` : "已保存的连接"}
        </p>
        <form
          role="search"
          className="search"
          onSubmit={(e) => {
            e.preventDefault();
            setQuery(search.trim());
            setPage(1);
          }}
        >
          <label className="search-input">
            <span className="sr-only">搜索连接名称</span>
            <Icon name="search" size={17} />
            <Input
              type="search"
              name="q"
              value={search}
              placeholder="搜索连接名称…"
              onChange={(e) => {
                setSearch(e.target.value);
                if (!e.target.value) {
                  setQuery("");
                  setPage(1);
                }
              }}
            />
          </label>
          <Button>搜索</Button>
          {query && (
            <Button
              type="button"
              onClick={() => {
                setSearch("");
                setQuery("");
                setPage(1);
              }}
            >
              清除
            </Button>
          )}
        </form>
      </div>
      <ErrorBox error={q.error} />
      {q.isPending && <Loading />}
      {q.data?.items.map((c) => (
        <ConnectorCard
          key={c.id}
          connector={c}
          onDeleted={() => {
            setNotice(`已删除连接「${c.name}」。`);
            if (q.data.items.length === 1 && page > 1) setPage(page - 1);
          }}
        />
      ))}
      {q.data && !q.data.items.length && (
        <Empty
          title={query ? "没有找到匹配的连接" : "连接第一个 GitHub 仓库"}
          icon="branch"
        >
          {query
            ? "换一个连接名称，或清除搜索条件。"
            : "添加 GitHub 令牌后，即可检查权限并为应用关联仓库。"}
        </Empty>
      )}
      {q.data && (q.data.total > q.data.page_size || page > 1) && (
        <Pager data={q.data} page={page} setPage={setPage} />
      )}
      <PermissionGuide />
      <GitHubAppSetup />
      <Dialog
        open={creating}
        busy={saving}
        title="新建 GitHub 连接"
        onClose={() => setCreating(false)}
      >
        <ConnectorForm
          onPendingChange={setSaving}
          onSaved={(c) => {
            setCreating(false);
            setQuery("");
            setSearch("");
            setPage(1);
            setNotice(
              `已创建连接「${c.name}」。填写目标仓库，继续检查读取权限。`,
            );
          }}
          onCancel={() => setCreating(false)}
        />
      </Dialog>
    </div>
  );
}

function ConnectorForm({
  connector,
  onSaved,
  onCancel,
  onDelete,
  onPendingChange,
}: {
  connector?: DTO<"Connector">;
  onSaved: (c: DTO<"Connector">) => void;
  onCancel: () => void;
  onDelete?: () => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const cmd = useCommand();
  const [version, setVersion] = useState(0);
  return (
    <>
      <p className="muted">
        {connector
          ? "修改名称或替换令牌。保存后请重新检查目标仓库权限。"
          : "使用个人访问令牌（PAT）连接 GitHub。令牌加密保存，保存后不会再次显示。"}
      </p>
      {cmd.feedback}
      <Form
        submit={(f) => {
          onPendingChange(true);
          void cmd
            .run(
              `connector-save-${version}`,
              (key) =>
                connector
                  ? write(
                      "/api/v1/connectors/github/{id}",
                      "patch",
                      {
                        name: text(f, "name"),
                        enabled: f.has("enabled"),
                        ...(text(f, "token")
                          ? { token: text(f, "token") }
                          : {}),
                      },
                      { id: connector.id, revision: connector.revision },
                    )
                  : write(
                      "/api/v1/connectors/github",
                      "post",
                      {
                        name: text(f, "name"),
                        token: text(f, "token"),
                        enabled: true,
                      },
                      { key },
                    ),
              onSaved,
              "",
            )
            .finally(() => onPendingChange(false));
        }}
      >
        <fieldset
          className="connector-fields"
          disabled={cmd.pending}
          onChange={() => setVersion((v) => v + 1)}
        >
          <Field
            label="连接名称"
            name="name"
            defaultValue={connector?.name}
            required
            maxLength={100}
            pattern=".*\S.*"
            validationMessage="请填写连接名称，不能只包含空格。"
            placeholder="例如：团队发布仓库"
            autoFocus
          />
          {connector?.auth_kind !== "github_app" && (
            <Field
              label={connector ? "替换令牌（可选）" : "GitHub 令牌（PAT）"}
              name="token"
              type="password"
              required={!connector}
              minLength={16}
              maxLength={4096}
              autoComplete="off"
              spellCheck={false}
              help={
                connector
                  ? "留空保留现有令牌。新令牌通过身份验证后才会替换。"
                  : "至少 16 个字符。需要 Contents 读取权限。"
              }
            />
          )}
          {connector && (
            <div>
              <Check
                name="enabled"
                label="启用此连接"
                defaultChecked={connector.enabled}
              />
              <p className="muted connector-field-help">
                停用后，关联应用将无法通过此连接同步或下载新的安装包。
              </p>
            </div>
          )}
          <PermissionGuide />
        </fieldset>
        <div className="connector-form-actions">
          {onDelete && (
            <Button
              type="button"
              className="danger connector-delete"
              disabled={cmd.pending}
              onClick={onDelete}
            >
              删除连接…
            </Button>
          )}
          <Button type="button" disabled={cmd.pending} onClick={onCancel}>
            取消
          </Button>
          <Button className="primary" disabled={cmd.pending}>
            {cmd.pending ? "正在保存…" : connector ? "保存修改" : "创建连接"}
          </Button>
        </div>
      </Form>
    </>
  );
}

type TestSnapshot = {
  result: DTO<"ConnectionTestResult">;
  repository: string;
  actions: boolean;
  revision: number;
};
function ConnectorCard({
  connector: c,
  onDeleted,
}: {
  connector: DTO<"Connector">;
  onDeleted: () => void;
}) {
  const testCmd = useCommand();
  const deleteCmd = useCommand();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [repository, setRepository] = useState("");
  const [actions, setActions] = useState(true);
  const [snapshot, setSnapshot] = useState<TestSnapshot>();
  const headingId = useId();
  const current = snapshot?.revision === c.revision ? snapshot : undefined;
  const changed =
    !!current &&
    (current.repository !== repository.trim() || current.actions !== actions);
  const failed =
    current?.result.checks.filter((check) => check.status === "fail").length ??
    0;
  const badge = !c.enabled
    ? "已停用"
    : testCmd.pending
      ? "正在检查"
      : current
        ? changed
          ? "待重新检查"
          : current.result.status === "ok"
            ? "检查通过"
            : current.result.status === "partial"
              ? "部分待验证"
              : `${failed} 项未通过`
        : c.last_test_status === "failed"
          ? "上次检查未通过"
          : c.last_tested_at
            ? "待重新检查"
            : "尚未检查";
  const tone =
    !c.enabled || changed
      ? "neutral"
      : current?.result.status === "failed" ||
          (!current && c.last_test_status === "failed")
        ? "fail"
        : current?.result.status === "ok"
          ? "pass"
          : "neutral";
  const codes = [
    "identity",
    "repository",
    "contents",
    "assets",
    ...(actions ? ["actions"] : []),
  ];
  return (
    <Panel className="panel connector-card" aria-labelledby={headingId}>
      <header className="connector-card-heading">
        <span className="connector-mark">
          <Icon name="branch" size={23} />
        </span>
        <div className="connector-identity">
          <h2 id={headingId}>{c.name}</h2>
          <p>
            {c.github_login ? `@${c.github_login}` : "尚未验证账号"}
            <span>·</span>
            {c.has_token ? "令牌已加密保存" : "尚未保存令牌"}
          </p>
        </div>
        <Badge className={tone}>{badge}</Badge>
        <Button
          disabled={testCmd.pending}
          onClick={() => {
            setSaved(false);
            setEditing(true);
          }}
        >
          编辑连接
        </Button>
      </header>
      {saved && (
        <Notice className="notice success" role="status">
          连接已保存。请重新检查仓库权限。
        </Notice>
      )}
      {!c.enabled && (
        <Notice className="notice">
          此连接已停用。请在「编辑连接」中启用后再检查。
        </Notice>
      )}
      <div className="connector-workspace">
        <div className="connector-test-config">
          <h3>检查读取权限</h3>
          <p className="muted">
            使用已保存的令牌，检查 Fuma 能否读取这个仓库的发布内容。
          </p>
          <Form
            submit={() => {
              const target = repository.trim();
              setSaved(false);
              setSnapshot(undefined);
              void testCmd.run(
                "connector-test",
                () =>
                  write(
                    "/api/v1/connectors/github/{id}/test",
                    "post",
                    {
                      check_actions: !!target && actions,
                      ...(target ? { repository_full_name: target } : {}),
                    },
                    { id: c.id },
                  ),
                (result) =>
                  setSnapshot({
                    result,
                    repository: target,
                    actions,
                    revision: c.revision,
                  }),
                "",
              );
            }}
          >
            <fieldset
              disabled={testCmd.pending || !c.enabled}
              className="connector-fields"
            >
              <Field
                label="目标仓库"
                name="repository_full_name"
                value={repository}
                onChange={(e) => setRepository(e.target.value)}
                placeholder="owner/repository"
                pattern="[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+"
                validationMessage="请填写 owner/repository，例如 Suvern/Joice；不要填写完整网址。"
                autoComplete="off"
                spellCheck={false}
                help="留空时，仅验证 GitHub 账号身份。"
              />
              <Check
                name="check_actions"
                label="同时检查 Actions 构建记录"
                checked={actions}
                disabled={!repository.trim()}
                onChange={(e) => setActions(!!e.target.checked)}
              />
              <Button
                className="primary"
                disabled={testCmd.pending || !c.enabled}
              >
                <Icon name="refresh" size={16} />
                {testCmd.pending
                  ? "正在检查…"
                  : current
                    ? "重新检查"
                    : "检查连接"}
              </Button>
            </fieldset>
          </Form>
          {testCmd.feedback}
          <p className="connector-test-time muted">
            {current
              ? `检查于 ${date(current.result.tested_at)}`
              : c.last_tested_at
                ? `上次检查 ${date(c.last_tested_at)}`
                : "尚无检查记录"}
          </p>
        </div>
        <div className="connector-diagnostics" aria-busy={testCmd.pending}>
          <div
            className="connector-result-heading"
            role="status"
            aria-live="polite"
          >
            <h3>
              {testCmd.pending
                ? "正在连接 GitHub…"
                : changed
                  ? "检查条件已更改"
                  : current
                    ? current.result.status === "ok"
                      ? "所选检查全部通过"
                      : failed
                        ? "需要处理以下问题"
                        : "部分项目尚待验证"
                    : "权限检查清单"}
            </h3>
            <p className="muted">
              {testCmd.pending
                ? "正在验证身份与读取权限，请稍候。"
                : changed
                  ? `下方是 ${current?.repository || "仅身份验证"} 的上次结果，请重新检查。`
                  : current
                    ? `${current.repository || "仅身份验证"} · ${current.result.checks.filter((x) => x.status === "pass").length} 项通过${failed ? ` · ${failed} 项未通过` : ""}`
                    : "检查后将在这里显示每一项的结果与修复方法。"}
            </p>
          </div>
          <ul className="connector-checks">
            {(
              current?.result.checks ??
              codes.map((code) => ({
                code,
                status: "unknown" as const,
                message: checkDescriptions[code] ?? "等待检查",
              }))
            ).map((check) => (
              <Diagnostic key={check.code} check={check} untested={!current} />
            ))}
          </ul>
        </div>
      </div>
      {c.auth_kind === "github_app" && <GitHubAppSetup connector={c} />}
      <Dialog
        open={editing}
        busy={saving}
        title={`编辑连接 · ${c.name}`}
        onClose={() => setEditing(false)}
      >
        <ConnectorForm
          onPendingChange={setSaving}
          connector={c}
          onSaved={() => {
            setEditing(false);
            setSnapshot(undefined);
            setSaved(true);
          }}
          onCancel={() => setEditing(false)}
          onDelete={() => {
            setEditing(false);
            setDeleting(true);
          }}
        />
      </Dialog>
      <Dialog
        open={deleting}
        busy={deleteCmd.pending}
        title={`删除连接「${c.name}」？`}
        onClose={() => {
          if (!deleteCmd.pending) setDeleting(false);
        }}
      >
        <p>
          这会移除已保存的 GitHub
          令牌，且无法撤销。已关联应用或安装包的连接不能删除，可改为停用。
        </p>
        {deleteCmd.feedback}
        <div className="connector-form-actions">
          <Button
            autoFocus
            disabled={deleteCmd.pending}
            onClick={() => setDeleting(false)}
          >
            取消
          </Button>
          <Button
            className="danger"
            disabled={deleteCmd.pending}
            onClick={() =>
              void deleteCmd.run(
                "connector-delete",
                () =>
                  write("/api/v1/connectors/github/{id}", "delete", undefined, {
                    id: c.id,
                    revision: c.revision,
                  }),
                onDeleted,
                "",
              )
            }
          >
            {deleteCmd.pending ? "正在删除…" : "删除连接"}
          </Button>
        </div>
      </Dialog>
    </Panel>
  );
}

function Diagnostic({
  check,
  untested,
}: {
  check: DTO<"Check">;
  untested: boolean;
}) {
  const status = untested ? "neutral" : check.status;
  return (
    <li className={`connector-check ${status}`}>
      <span className="connector-check-symbol" aria-hidden="true">
        {status === "pass" ? (
          <Icon name="check" size={17} />
        ) : status === "fail" ? (
          "!"
        ) : (
          "—"
        )}
      </span>
      <div className="connector-check-body">
        <div className="connector-check-title">
          <strong>{checkNames[check.code] ?? check.code}</strong>
          <span>
            {untested
              ? "待检查"
              : check.status === "pass"
                ? "通过"
                : check.status === "fail"
                  ? "未通过"
                  : "未验证"}
          </span>
        </div>
        <p>{check.message}</p>
        {check.status === "fail" && (
          <div className="connector-remediation">
            {check.required_permission && (
              <p>
                所需权限 <strong>{check.required_permission}</strong>
              </p>
            )}
            <p>
              {check.remediation ||
                "重新检查此项；若仍未通过，请核对令牌的仓库访问范围与对应读取权限。"}
            </p>
            {(!check.error_code ||
              [
                "GITHUB_FORBIDDEN",
                "GITHUB_NOT_FOUND",
                "GITHUB_BAD_CREDENTIAL",
                "GITHUB_SSO_REQUIRED",
              ].includes(check.error_code)) && (
              <a href={tokenSettings} target="_blank" rel="noreferrer">
                前往 GitHub 检查令牌 <Icon name="external" size={13} />
              </a>
            )}
            {(check.error_code || check.endpoint) && (
              <Disclosure title={<>诊断详情</>}>
                <p>
                  <code>{check.error_code}</code>
                </p>
                <p>
                  <code>{check.endpoint}</code>
                </p>
              </Disclosure>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

function GitHubAppSetup({ connector }: { connector?: DTO<"Connector"> }) {
  const cmd = useCommand();
  const [formKey, setFormKey] = useState(0);
  return (
    <Panel>
      <details>
        <summary>
          {connector ? "轮换 GitHub App 私钥" : "通过 GitHub App 安装授权接入"}
        </summary>
        <p>
          在 GitHub 创建自己的 App，为目标仓库授予 Contents · Read-only 和
          Actions · Read-only，并完成安装。这里填入 App ID、安装 ID 与 RSA
          私钥；后台按需签发短效安装令牌，不会向浏览器返回私钥或令牌。
        </p>
        <a
          href="https://github.com/settings/apps"
          target="_blank"
          rel="noreferrer"
        >
          打开 GitHub App 设置
        </a>
        {cmd.feedback}
        <Form
          key={formKey}
          submit={(form) =>
            void cmd.run(
              "github-app-save",
              () => {
                const values = {
                  app_id: connector?.app_id || text(form, "app_id"),
                  installation_id:
                    connector?.installation_id || text(form, "installation_id"),
                  private_key: text(form, "private_key"),
                };
                return connector
                  ? write(
                      "/api/v1/connectors/github/{id}/app-credentials",
                      "put",
                      values,
                      { id: connector.id, revision: connector.revision },
                    )
                  : write("/api/v1/connectors/github-app", "post", {
                      name: text(form, "name"),
                      ...values,
                    });
              },
              () => setFormKey((k) => k + 1),
              "安装身份验证通过，配置已保存。请继续检查目标仓库权限。",
            )
          }
        >
          {!connector && (
            <>
              <Field name="name" label="连接名称" required maxLength={100} />
              <Field
                name="app_id"
                label="GitHub App ID"
                required
                pattern="[0-9]+"
              />
              <Field
                name="installation_id"
                label="Installation ID（安装页面地址末尾的数字）"
                required
                pattern="[0-9]+"
              />
            </>
          )}
          {connector && (
            <p>
              App {connector.app_id} · 安装 {connector.installation_id}
            </p>
          )}
          <label>
            RSA 私钥 PEM
            <TextArea
              name="private_key"
              autoComplete="off"
              spellCheck={false}
              required
              minLength={100}
              maxLength={20000}
              rows={4}
            />
          </label>
          <p>仅在此处粘贴，保存后清空。新私钥验证失败时保留原配置。</p>
          <Button className="primary" disabled={cmd.pending}>
            验证并保存
          </Button>
        </Form>
      </details>
    </Panel>
  );
}
