import { Link, Outlet } from "react-router";
import { LogoutButton } from "../../features/m1/Auth";
import { useSession } from "../../shared/ui/common";
export function PublicLayout() {
  const session = useSession();
  return (
    <>
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <header className="site-header">
        <Link className="brand" to="/">
          <span className="brand-mark">F</span> Fuma
        </Link>
        <nav aria-label="主要">
          <Link to="/admin">管理入口</Link>
          {session.data?.authenticated && (
            <>
              <span>{session.data.user?.display_name}</span>
              <LogoutButton />
            </>
          )}
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer>Fuma · 移动端安装包管理</footer>
    </>
  );
}
