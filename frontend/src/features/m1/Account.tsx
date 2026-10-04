import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { read, write } from "../../shared/api/http";
import { Button, Panel } from "../../shared/ui/controls";
import {
  ErrorBox,
  Loading,
  Pager,
  Title,
  date,
  useCommand,
  useSession,
} from "../../shared/ui/common";
import { LogoutButton, PasswordPage } from "./Auth";
import { roleNames } from "./permissions";

export function AccountPage() {
  const session = useSession();
  if (session.isPending) return <Loading />;
  if (session.error) return <ErrorBox error={session.error} />;
  const user = session.data?.user;
  if (!user) return null;
  if (user.must_change_password) return <PasswordPage />;
  return (
    <>
      <Title description="管理当前身份与自己的登录会话。">账号与会话</Title>
      <Panel>
        <h2>{user.display_name}</h2>
        <p>
          {user.kind === "local" ? "本地账号" : "飞书账号"} ·{" "}
          {roleNames[user.role]}
        </p>
        <p>
          {user.role === "admin"
            ? "管理范围：全部应用与全局设置"
            : `管理范围：${user.managed_app_ids?.length ?? 0} 个获授权应用`}
        </p>
        {user.role === "maintainer" && (
          <Link to="/admin/apps">查看我的应用</Link>
        )}
        <LogoutButton />
      </Panel>
      <OwnSessions />
      {user.kind === "local" && (
        <details className="panel">
          <summary>修改本地密码</summary>
          <PasswordPage />
        </details>
      )}
    </>
  );
}

function OwnSessions() {
  const session = useSession();
  const [page, setPage] = useState(1);
  const cmd = useCommand();
  const query = useQuery({
    queryKey: ["own-sessions", session.data?.viewer_key, page],
    queryFn: () => read("/api/v1/auth/sessions", { query: { page } }),
  });
  return (
    <Panel>
      <h2>登录会话</h2>
      <p className="muted">
        仅显示自己的会话。未采集客户端设备信息，不据此推断设备或登录地点。
      </p>
      {cmd.feedback}
      <ErrorBox error={query.error} />
      <Button
        disabled={cmd.pending || query.isPending}
        onClick={() =>
          void cmd.run(
            "revoke-others",
            () =>
              write("/api/v1/auth/sessions/revoke-others", "post", undefined),
            () => setPage(1),
            "其他活动会话已注销，当前登录保留。",
            "注销此账号的其他活动会话？其他浏览器需重新登录，当前会话保留。",
          )
        }
      >
        注销其他会话
      </Button>
      <Button disabled={query.isFetching} onClick={() => void query.refetch()}>
        刷新会话
      </Button>
      {query.isPending && <Loading />}
      {query.data?.items.map((item) => (
        <div key={item.id} className="panel">
          <strong>{item.current ? "当前会话" : "其他会话"}</strong> ·{" "}
          {{ active: "有效", expired: "已过期", revoked: "已注销" }[item.state]}
          <p>
            登录于 {date(item.authenticated_at ?? item.created_at)} · 到期{" "}
            {date(item.expires_at)}
          </p>
          {item.revoked_at && <p>注销于 {date(item.revoked_at)}</p>}
        </div>
      ))}
      <Pager data={query.data} page={page} setPage={setPage} />
    </Panel>
  );
}
