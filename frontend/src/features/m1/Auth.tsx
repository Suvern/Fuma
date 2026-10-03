import { Panel, Notice, Button, Disclosure } from "../../shared/ui/controls";
import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router";
import { Fragment } from "react";
import { BrandMark, Icon } from "../../shared/ui/Icon";
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
  const status = useQuery({
    queryKey: ["bootstrap"],
    queryFn: () => read("/api/v1/auth/bootstrap-status"),
  });
  const cmd = useCommand();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const returnTo = safeReturnPath(params.get("return_to"));
  if (status.isPending) return <Loading />;
  if (status.error) return <ErrorBox error={status.error} />;
  return (
    <Panel className="auth-card panel login-card">
      <div className="auth-symbol">
        <BrandMark />
      </div>
      <Title>管理员登录</Title>
      <p className="muted">欢迎回来，继续管理团队的应用与分发。</p>
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
      {params.has("error") && (
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
      )}
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
        <a className="button" href={ssoUrl(returnTo)}>
          使用飞书访问 Debug 下载
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
  if (session.data?.user?.role !== "admin")
    return (
      <Navigate
        to={`/login?return_to=${encodeURIComponent(requestedPath)}`}
        replace
      />
    );
  // Do not mount protected descendants until the first-password requirement is met.
  if (
    session.data.user.must_change_password &&
    location.pathname !== accountPath
  )
    return <Navigate to={passwordPath(requestedPath)} replace />;
  return children;
}

export function DownloadGuard({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const status = useQuery({
    queryKey: ["bootstrap"],
    queryFn: () => read("/api/v1/auth/bootstrap-status"),
  });
  if (session.isPending || status.isPending) return <Loading />;
  if (session.error) return <ErrorBox error={session.error} />;
  if (status.error) return <ErrorBox error={status.error} />;
  if (!status.data?.initialized) return <Navigate to="/login" replace />;
  if (session.data?.user?.kind !== "feishu")
    return (
      <Panel className="panel auth-card">
        <Title description="仅部署绑定的飞书租户成员可查看和下载安装包。">
          Debug 下载
        </Title>
        {status.data.sso_enabled ? (
          <a className="button primary" href={ssoUrl()}>
            使用飞书登录
          </a>
        ) : (
          <Notice className="notice">
            飞书登录尚未启用，请联系管理员完成接入配置。
          </Notice>
        )}
        {status.data.sso_enabled && session.data?.user?.role === "admin" && (
          <p className="muted">继续登录将切换当前浏览器的管理员会话。</p>
        )}
        <p>
          <Link to="/login">管理员入口</Link>
        </p>
      </Panel>
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
