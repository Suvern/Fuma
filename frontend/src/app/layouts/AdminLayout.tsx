import { Link, NavLink, Outlet } from "react-router";
import { AdminGuard, LogoutButton } from "../../features/m1/Auth";
const items: [string, string][] = [
  ["/admin", "工作台"],
  ["/admin/apps", "应用管理"],
  ["/admin/connectors", "GitHub Connector"],
  ["/admin/settings/feishu", "飞书与机器人"],
  ["/admin/notifications", "通知记录"],
  ["/admin/tasks", "任务中心"],
  ["/admin/settings/cache", "本地缓存"],
  ["/admin/audit", "审计日志"],
  ["/admin/settings/account", "账号安全"],
];
export function Component() {
  return (
    <AdminGuard>
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <div className="admin-shell">
        <aside className="sidebar">
          <Link className="brand" to="/admin">
            <span className="brand-mark">F</span> Fuma <small>控制台</small>
          </Link>
          <nav aria-label="管理导航">
            {items.map(([to, title]) => (
              <NavLink end={to === "/admin"} key={to} to={to}>
                {title}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <Link to="/">打开下载门户 ↗</Link>
            <LogoutButton />
          </div>
        </aside>
        <div className="admin-content">
          <header className="admin-topbar">
            <span>移动端安装包管理</span>
            <span className="badge">M1 · Debug 分发</span>
          </header>
          <main id="main" tabIndex={-1}>
            <Outlet />
          </main>
          <footer>Fuma · 团队的安装包，从构建到设备。</footer>
        </div>
      </div>
    </AdminGuard>
  );
}
