import { Panel, Notice, Button, Disclosure } from "../../shared/ui/controls";
import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router";
import { Fragment, useEffect, useState } from "react";
import { canManage, globalOnlyPath, isGlobalAdmin } from "./permissions";
import { BrandMark, Icon } from "../../shared/ui/Icon";
import "./auth.css";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  read,
  write,
  safeReturnPath,
  ssoUrl,
} from "../../shared/api/http";
import {
  ErrorBox,
  Field,
  Form,
  Loading,
  Title,
  useCommand,
  useSession,
} from "../../shared/ui/common";

const accountPath = "/admin/settings/account";
function destination(value: string | null) {
  const path = safeReturnPath(value);
  return path === "/" ||
    path.split("?")[0] === accountPath ||
    path.split("?")[0] === "/login"
    ? "/admin"
    : path;
}
function passwordPath(returnTo: string) {
  return `${accountPath}?return_to=${encodeURIComponent(destination(returnTo))}`;
}

export function LoginPage() {
  const session = useSession();
  const status = useQuery({
    queryKey: ["bootstrap"],
    queryFn: () => read("/api/v1/auth/bootstrap-status"),
  });
  const cmd = useCommand();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const returnTo = safeReturnPath(params.get("return_to"));
  if (session.isPending || status.isPending) return <Loading />;
  if (session.error) return <ErrorBox error={session.error} />;
  if (status.error) return <ErrorBox error={status.error} />;
  const loginError = params.has("error") && (
    <Notice role="alert" className="notice error">
      飞书验证未完成。请确认账号属于当前部署租户，并重试飞书登录。
      {returnTo === "/admin/settings/feishu" ? (
        <Link to={returnTo}>返回接入设置</Link>
      ) : (
        status.data?.sso_enabled && (
          <a href={ssoUrl(returnTo)}>重新验证飞书资格</a>
        )
      )}
    </Notice>
  );
  if (session.data?.authenticated) {
    const manage = canManage(session.data.user);
    const path = new URL(returnTo, window.location.origin).pathname.replace(/\/+$/, "");
    const target = !path || path === "/login"
      ? manage ? "/admin" : "/"
      : !manage && (path === "/admin" || path.startsWith("/admin/"))
        ? "/"
        : returnTo;
    if (session.data.user?.must_change_password)
      return <Navigate to={passwordPath(target)} replace />;
    // A failed account binding must remain actionable without asking the
    // already authenticated user to enter their password again.
    if (loginError)
      return (
        <Panel className="panel auth-card">
          <Title>飞书验证未完成</Title>
          {loginError}
          <Link to={target}>{manage ? "继续进入后台" : "返回下载首页"}</Link>
        </Panel>
      );
    return <Navigate to={target} replace />;
  }
  return (
    <Panel className="auth-card panel login-card">
      <header className="login-intro">
        <div className="auth-brand">
          <BrandMark />
          <span className="auth-brand-name">Fuma</span>
        </div>
        <Title>后台登录</Title>
        <p className="muted">欢迎回来，继续管理团队的应用与分发。</p>
      </header>
      {!status.data?.initialized && (
        <Notice role="status" className="notice">
          服务正在初始化管理员，请稍后刷新。
          <Button
            type="button"
            onClick={() => void status.refetch()}
            disabled={status.isFetching}
          >
            刷新状态
          </Button>
        </Notice>
      )}
      {loginError}
      {cmd.feedback}
      <Form
        submit={(f) => {
          if (!status.data?.initialized) return;
          void cmd.run(
            "auth",
            () =>
              write("/api/v1/auth/login", "post", {
                username: "admin",
                password: String(f.get("password") ?? ""),
              }),
            (session) => {
              client.clear();
              navigate(
                session.user.must_change_password
                  ? passwordPath(returnTo)
                  : returnTo === "/"
                    ? "/admin"
                    : returnTo,
                { replace: true },
              );
            },
          );
        }}
      >
        <Field
          label="管理员账号"
          name="username"
          value="admin"
          readOnly
          autoComplete="username"
        />
        <Field
          label="密码"
          id="current-password"
          name="password"
          type="password"
          required
          minLength={1}
          maxLength={128}
          autoComplete="current-password"
        />
        <Button
          className="primary"
          disabled={cmd.pending || !status.data?.initialized}
        >
          {cmd.pending ? "正在提交…" : "登录后台"}
        </Button>
      </Form>
      <Disclosure title={<>首次登录或忘记密码？</>} className="login-help">
        <p>
          首次启动会创建 admin 账号，初始密码仅显示在 API
          启动日志中，首次登录后需修改密码。
        </p>
        <p>
          Docker 部署可运行{" "}
          <code>
            docker compose --env-file .env -f deploy/compose.yml logs api
          </code>{" "}
          查看首次启动日志。忘记密码时请联系服务器管理员重置。
        </p>
      </Disclosure>
      {status.data?.sso_enabled && (
        <a
          className="button"
          href={ssoUrl(returnTo === "/" ? "/admin" : returnTo)}
        >
          使用飞书登录
        </a>
      )}
      <p>
        <Link to="/">返回下载首页</Link>
      </p>
    </Panel>
  );
}

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const location = useLocation();
  const requestedPath = location.pathname + location.search;
  if (session.isPending) return <Loading />;
  if (session.error) return <ErrorBox error={session.error} />;
  if (!session.data?.authenticated)
    return (
      <Navigate
        to={`/login?return_to=${encodeURIComponent(requestedPath)}`}
        replace
      />
    );
  if (!canManage(session.data.user))
    return (
      <Panel className="panel">
        <Title>暂无后台权限</Title>
        <p>
          当前账号仅可按下载权限访问前台。如需维护应用，请联系管理员分配后台角色。
        </p>
        <Link to="/">前往下载门户</Link>
        <LogoutButton />
      </Panel>
    );
  if (!isGlobalAdmin(session.data.user) && globalOnlyPath(location.pathname))
    return (
      <Panel className="panel">
        <Title>此页面需要管理员权限</Title>
        <p>你可以管理获授权的应用、安装包、版本和任务。</p>
        <Link to="/admin/apps">返回我的应用</Link>
      </Panel>
    );
  // Do not mount protected descendants until the first-password requirement is met.
  if (
    session.data.user?.must_change_password &&
    location.pathname !== accountPath
  )
    return <Navigate to={passwordPath(requestedPath)} replace />;
  return (
    <ManagementScope
      scope={`${session.data.viewer_key}:${session.data.user?.role}:${session.data.user?.permission_revision ?? 1}`}
    >
      {children}
    </ManagementScope>
  );
}

function ManagementScope({
  scope,
  children,
}: {
  scope: string;
  children: React.ReactNode;
}) {
  const client = useQueryClient();
  const [visibleScope, setVisibleScope] = useState<string | null>(null);
  useEffect(() => {
    if (visibleScope === scope) return;
    let active = true;
    void client
      .cancelQueries({ predicate: (query) => query.queryKey[0] !== "session" })
      .then(() => {
        client.removeQueries({
          predicate: (query) => query.queryKey[0] !== "session",
        });
        if (active) setVisibleScope(scope);
      });
    return () => {
      active = false;
    };
  }, [scope, visibleScope, client]);
  return visibleScope === scope ? children : <Loading />;
}

export function DownloadGuard({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const location = useLocation();
  const status = useQuery({
    queryKey: ["bootstrap"],
    queryFn: () => read("/api/v1/auth/bootstrap-status"),
  });
  if (session.isPending || status.isPending) return <Loading />;
  if (session.error) return <ErrorBox error={session.error} />;
  if (status.error) return <ErrorBox error={status.error} />;
  if (!status.data?.initialized) return <Navigate to="/login" replace />;
  if (session.data?.authenticated && session.data.user?.must_change_password)
    return <Navigate to={passwordPath(location.pathname + location.search)} replace />;
  if (!session.data?.authenticated)
    return (
      <section className="download-welcome" aria-labelledby="download-login-title">
        <div className="download-welcome-heading">
          <span className="download-eyebrow">FUMA / 团队应用分发</span>
          <h1 id="download-login-title">好版本，即刻体验。</h1>
          <p>连接团队，获取最新的 Android 与 iOS 测试版。</p>
        </div>
        <Panel className="panel download-login-card">
          <div className="download-brand-mark"><BrandMark /></div>
          <h2>登录下载测试版</h2>
          <p className="download-login-description">使用团队飞书账号，查看和下载 Debug 安装包。</p>
          {status.data.sso_enabled ? (
            <a className="button primary download-sso-button" href={ssoUrl()}>
              <Icon name="chat" size={20} />
              <span>使用飞书登录</span>
              <Icon name="arrow" size={18} />
            </a>
          ) : (
            <Notice className="notice">
              飞书登录尚未启用，请联系管理员完成接入配置。
            </Notice>
          )}
          <p className="download-access-note"><Icon name="shield" size={15} />支持组织飞书成员或管理员访问</p>
          <div className="download-login-footer">
            <span>需要管理应用与分发？</span>
            <Link to="/login">管理员入口<Icon name="chevron" size={14} /></Link>
          </div>
        </Panel>
        <Link className="download-release-link" to="/releases">浏览已发布版本<Icon name="arrow" size={16} /></Link>
      </section>
    );
  return <Fragment key={session.data.viewer_key}>{children}</Fragment>;
}

export function LogoutButton({ compact = false }: { compact?: boolean }) {
  const cmd = useCommand();
  const client = useQueryClient();
  const navigate = useNavigate();
  return (
    <>
      <Button
        className={compact ? "icon-button" : undefined}
        aria-label={compact ? "退出登录" : undefined}
        title={compact ? "退出登录" : undefined}
        disabled={cmd.pending}
        onClick={() =>
          void cmd.run(
            "logout",
            () => write("/api/v1/auth/logout", "post", undefined),
            () => {
              client.clear();
              navigate("/login", { replace: true });
            },
          )
        }
      >
        {compact ? <Icon name="logout" size={17} /> : "退出登录"}
      </Button>
      {cmd.feedback}
    </>
  );
}

export function PasswordPage() {
  const cmd = useCommand();
  const client = useQueryClient();
  const navigate = useNavigate();
  const session = useSession();
  const [params] = useSearchParams();
  const returnTo = destination(params.get("return_to"));
  const mandatory = Boolean(session.data?.user?.must_change_password);
  if (session.isPending) return <Loading />;
  if (session.error) return <ErrorBox error={session.error} />;
  if (session.data?.user?.kind !== "local")
    return (
      <Panel className="panel">
        <p>飞书账号不使用本地密码，请在飞书管理登录凭据。</p>
      </Panel>
    );
  return (
    <>
      <Title
        description={
          mandatory
            ? "请先将初始密码改为你自己的密码，完成后才能访问后台功能。"
            : "修改密码会撤销旧会话，并更新当前登录会话。"
        }
      >
        {mandatory ? "首次登录：修改密码" : "账号安全"}
      </Title>
      <Panel className="panel">
        {cmd.feedback}
        <Form
          submit={(f) =>
            void cmd.run(
              "password",
              async () => {
                const oldPassword = String(f.get("old_password") ?? "");
                const newPassword = String(f.get("new_password") ?? "");
                if (oldPassword === newPassword)
                  throw new Error("新密码不能与当前密码相同。");
                if (newPassword !== String(f.get("confirm_password") ?? ""))
                  throw new Error("两次输入的新密码不一致。");
                await write("/api/v1/auth/password", "post", {
                  old_password: oldPassword,
                  new_password: newPassword,
                });
                await client.cancelQueries();
                try {
                  return await read("/api/v1/auth/browser-context");
                } catch (error) {
                  if (
                    error instanceof ApiError &&
                    [401, 403].includes(error.status)
                  )
                    return null;
                  throw error;
                }
              },
              (context) => {
                client.clear();
                if (context) client.setQueryData(["session"], context);
                if (
                  context?.authenticated &&
                  context.user?.role === "admin" &&
                  !context.user.must_change_password
                ) {
                  navigate(returnTo, { replace: true });
                } else if (
                  context?.authenticated &&
                  context.user?.must_change_password
                ) {
                  navigate(passwordPath(returnTo), { replace: true });
                } else {
                  navigate(`/login?return_to=${encodeURIComponent(returnTo)}`, {
                    replace: true,
                  });
                }
              },
            )
          }
        >
          <Field
            label="当前密码"
            id="current-password"
            name="old_password"
            required
            type="password"
            autoComplete="current-password"
            help={
              mandatory
                ? "首次登录时填写 API 启动日志中的随机初始密码。"
                : undefined
            }
          />
          <Field
            label="新密码"
            id="new-password"
            name="new_password"
            required
            type="password"
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
            help="至少 12 位，且不能与当前密码相同。"
          />
          <Field
            label="确认新密码"
            name="confirm_password"
            required
            type="password"
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
          />
          <Button className="primary" disabled={cmd.pending}>
            {cmd.pending ? "正在修改…" : "修改密码"}
          </Button>
        </Form>
      </Panel>
    </>
  );
}

export function AuthErrorPage() {
  return (
    <Panel className="panel">
      <Title>飞书登录未完成</Title>
      <p>
        登录已取消、授权已失效或账号不属于当前部署租户，请重试。管理员可检查飞书应用配置及可用范围。
      </p>
      <a className="button primary" href={ssoUrl("/")}>
        重新登录飞书
      </a>
      <Link to="/admin/settings/feishu">检查配置</Link>
    </Panel>
  );
}
