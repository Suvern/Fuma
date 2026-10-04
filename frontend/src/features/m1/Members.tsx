import { Select } from "../../shared/ui/FormControls";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { Dialog } from "../../shared/ui/Dialog";
import { Button, Panel } from "../../shared/ui/controls";
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
  useSession,
} from "../../shared/ui/common";
import { isGlobalAdmin, roleNames } from "./permissions";

export function MembersPage() {
  const session = useSession();
  if (session.isPending) return <Loading />;
  if (!isGlobalAdmin(session.data?.user))
    return (
      <Panel>
        <Title>需要管理员权限</Title>
        <Link to="/admin/apps">返回我的应用</Link>
      </Panel>
    );
  return <Members />;
}

function Members() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    q: "",
    role: "",
    active: "",
    app_id: "",
  });
  const [editing, setEditing] = useState<DTO<"MemberInfo">>();
  const [pending, setPending] = useState(false);
  const query = useQuery({
    queryKey: ["members", page, filters],
    queryFn: () =>
      read("/api/v1/settings/members", {
        query: {
          page,
          q: filters.q || undefined,
          role: filters.role || undefined,
          active: filters.active || undefined,
          app_id: filters.app_id || undefined,
        },
      }),
  });
  return (
    <>
      <Title description="后台角色与下载资格相互独立；授予维护权限不会自动开放下载安装包。">
        成员与角色
      </Title>
      <Panel>
        <p>
          添加授权成员：请先让对方使用当前部署的飞书租户登录一次，再在列表中选择“编辑授权”。这里只管理
          Fuma 后台权限，不创建或删除飞书人员。
        </p>
        <p className="muted">尚未验证当前租户身份的成员只能撤权或停用。</p>
        <Link to="/admin/settings/feishu">检查飞书接入</Link>
      </Panel>
      <Form
        submit={(form) => {
          setFilters({
            q: text(form, "q"),
            role: text(form, "role"),
            active: text(form, "active"),
            app_id: text(form, "app_id"),
          });
          setPage(1);
        }}
      >
        <div className="inline">
          <Field
            name="q"
            label="姓名或身份标识"
            maxLength={200}
            defaultValue={filters.q}
          />
          <div className="field">
            <Select label="后台角色" name="role" defaultValue={filters.role}>
              <option value="">全部角色</option>
              {Object.entries(roleNames).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </Select>
          </div>
          <div className="field">
            <Select
              label="账号状态"
              name="active"
              defaultValue={filters.active}
            >
              <option value="">全部状态</option>
              <option value="true">可用</option>
              <option value="false">停用</option>
            </Select>
          </div>
          <AppFilter />
          <Button>筛选</Button>
        </div>
      </Form>
      <Button disabled={query.isFetching} onClick={() => void query.refetch()}>
        刷新成员
      </Button>
      <ErrorBox error={query.error} />
      {query.isPending && <Loading />}
      {query.data && <p>共 {query.data.total} 位成员</p>}
      {query.data?.items.map((member) => (
        <Panel key={member.id}>
          <h2>{member.display_name}</h2>
          <p>
            {member.kind === "local" ? "本地救援账号" : "飞书身份"} ·{" "}
            {roleNames[member.role]} · {member.active ? "可用" : "停用"}
          </p>
          <p>
            {member.role === "admin"
              ? "授权范围：全部应用与全局设置"
              : member.role === "maintainer"
                ? `授权范围：${member.managed_app_ids.length} 个应用`
                : "无后台管理授权"}
          </p>
          <div className="inline">
            {member.managed_app_ids.map((id) => (
              <ManagedAppLink key={id} appId={id} />
            ))}
          </div>
          <p className="muted">
            权限更新：{date(member.permission_changed_at)}
            {member.kind === "feishu" &&
              ` · 当前租户身份${member.identity_verified ? "已验证" : "未验证"}`}
          </p>
          {member.kind === "local" ? (
            <p>内置本地救援账号不能撤销或停用。</p>
          ) : (
            <Button onClick={() => setEditing(member)}>编辑授权</Button>
          )}
          <Link to="/admin/audit">查看审计日志</Link>
        </Panel>
      ))}
      {query.data && !query.data.items.length && (
        <Empty>
          没有匹配的已登录成员。请调整筛选，或让成员先完成飞书登录。
        </Empty>
      )}
      <Pager data={query.data} page={page} setPage={setPage} />
      <Dialog
        open={!!editing}
        title="编辑后台授权"
        busy={pending}
        onClose={() => setEditing(undefined)}
      >
        {editing && (
          <RoleEditor
            key={editing.id}
            member={editing}
            onPending={setPending}
            onSaved={() => setEditing(undefined)}
            onRefresh={() => {
              setEditing(undefined);
              void query.refetch();
            }}
          />
        )}
      </Dialog>
    </>
  );
}

function ManagedAppLink({ appId }: { appId: string }) {
  const query = useQuery({
    queryKey: ["app", appId],
    queryFn: () => read("/api/v1/apps/{id}", { id: appId }),
  });
  return (
    <Link to={`/admin/apps/${appId}`}>
      {query.data?.name ??
        (query.isPending ? "加载应用名称…" : "查看已授权应用")}
    </Link>
  );
}

function AppFilter() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState({ id: "", name: "" });
  const query = useQuery({
    queryKey: ["member-filter-apps", page, search],
    queryFn: ({ signal }) =>
      read("/api/v1/apps", { query: { page, q: search }, signal }),
  });
  return (
    <div>
      <Field
        label="搜索筛选应用"
        type="search"
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setPage(1);
        }}
        placeholder="输入应用名称"
        maxLength={200}
      />
      <div className="field">
        <Select
          label="授权应用"
          name="app_id"
          value={selected.id}
          onChange={(event) => {
            const app = query.data?.items.find(
              (item) => item.id === event.target.value,
            );
            setSelected({ id: app?.id ?? "", name: app?.name ?? "" });
          }}
        >
          <option value="">全部应用</option>
          {selected.id &&
            !query.data?.items.some((app) => app.id === selected.id) && (
              <option value={selected.id}>{selected.name}</option>
            )}
          {query.data?.items.map((app) => (
            <option key={app.id} value={app.id}>
              {app.name}
            </option>
          ))}
        </Select>
      </div>
      <ErrorBox error={query.error} />
      {query.isPending && <p role="status">正在搜索应用…</p>}
      {query.data && !query.data.items.length && (
        <p>没有匹配的应用，请调整名称搜索。</p>
      )}
      <Pager data={query.data} page={page} setPage={setPage} />
    </div>
  );
}

function RoleEditor({
  member,
  onPending,
  onSaved,
  onRefresh,
}: {
  member: DTO<"MemberInfo">;
  onPending: (value: boolean) => void;
  onSaved: () => void;
  onRefresh: () => void;
}) {
  const [role, setRole] = useState(member.role);
  const [active, setActive] = useState(member.active);
  const [apps, setApps] = useState(member.managed_app_ids);
  const cmd = useCommand();
  useEffect(() => {
    onPending(cmd.pending);
    return () => onPending(false);
  }, [cmd.pending, onPending]);
  const names = `${member.display_name}：${roleNames[role]}，${active ? "账号可用" : "账号停用"}；${role === "admin" ? "可管理全部应用、成员和全局凭据" : role === "maintainer" ? `仅管理所选 ${apps.length} 个应用` : "没有后台管理权限"}`;
  const save = (
    nextRole = role,
    nextApps = role === "maintainer" ? apps : [],
    nextActive = active,
  ) => {
    void cmd.run(
      `role-${member.id}-${nextRole}-${nextApps.join(",")}-${nextActive}`,
      () =>
        write(
          "/api/v1/settings/members/{id}/roles",
          "put",
          { role: nextRole, managed_app_ids: nextApps, active: nextActive },
          { id: member.id, revision: member.permission_revision },
        ),
      onSaved,
      "授权已更新。",
      `${nextRole === "downloader" ? `${member.display_name}：撤销后台权限。` : names} 保存后立即停止不再允许的新操作；已提交第三方的任务不能保证撤销。`,
    );
  };
  return (
    <>
      <p>
        当前：{member.display_name} · {roleNames[member.role]} · 权限修订{" "}
        {member.permission_revision}
      </p>
      {!member.identity_verified && (
        <p role="status">
          当前租户身份尚未验证，只能设为仅下载用户或停用账号。
        </p>
      )}
      {cmd.feedback}
      <Form submit={() => save()}>
        <div className="field">
          <Select
            label="授予角色"
            value={role}
            disabled={cmd.pending}
            onChange={(e) =>
              setRole(e.target.value as DTO<"MemberInfo">["role"])
            }
          >
            {Object.entries(roleNames).map(([key, label]) => (
              <option
                key={key}
                value={key}
                disabled={!member.identity_verified && key !== "downloader"}
              >
                {label}
              </option>
            ))}
          </Select>
        </div>
        <Check
          label="账号可用"
          checked={active}
          onChange={(e) => setActive(!!e.target.checked)}
          disabled={cmd.pending}
        />
        {role === "maintainer" && (
          <AppSelection
            selected={apps}
            onChange={setApps}
            disabled={cmd.pending}
          />
        )}
        <p>{names}</p>
        <Button
          disabled={
            cmd.pending ||
            (role === "maintainer" && !apps.length) ||
            (!member.identity_verified && active && role !== "downloader")
          }
        >
          确认授权
        </Button>
      </Form>
      <Button
        className="danger"
        disabled={cmd.pending || member.role === "downloader"}
        onClick={() => save("downloader", [], member.active)}
      >
        撤销后台授权
      </Button>
      <Button disabled={cmd.pending} onClick={onRefresh}>
        放弃草稿并刷新权限
      </Button>
    </>
  );
}

function AppSelection({
  selected,
  onChange,
  disabled,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled: boolean;
}) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: ["member-app-options", page, search],
    queryFn: () =>
      read("/api/v1/apps", { query: { page, q: search, archived: false } }),
  });
  return (
    <fieldset disabled={disabled}>
      <legend>获授权应用（至少一个）</legend>
      <Field
        label="搜索应用"
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setPage(1);
        }}
      />
      <p>已选择 {selected.length} 个，跨分页保留。</p>
      <ErrorBox error={query.error} />
      {query.isPending && <Loading />}
      {query.data?.items.map((app) => (
        <Check
          key={app.id}
          label={app.name}
          checked={selected.includes(app.id)}
          onChange={(e) =>
            onChange(
              e.target.checked
                ? [...selected, app.id]
                : selected.filter((id) => id !== app.id),
            )
          }
        />
      ))}
      <Button type="button" onClick={() => onChange([])}>
        清空应用选择
      </Button>
      <Pager data={query.data} page={page} setPage={setPage} />
    </fieldset>
  );
}
