import Avatar from "@douyinfe/semi-ui-19/lib/es/avatar";
import Layout from "@douyinfe/semi-ui-19/lib/es/layout";
import Space from "@douyinfe/semi-ui-19/lib/es/space";
import Typography from "@douyinfe/semi-ui-19/lib/es/typography";
import SideSheet from "@douyinfe/semi-ui-19/lib/es/sideSheet";
import { useState } from "react";
import { Link, Outlet } from "react-router";
import { LogoutButton } from "../../features/m1/Auth";
import { FeishuAutoLogin } from "../../features/m1/FeishuAutoLogin";
import { useSession } from "../../shared/ui/common";
import { BrandMark, Icon } from "../../shared/ui/Icon";
import { Button } from "../../shared/ui/controls";
import "./public-layout.css";
export function PublicLayout() {
  const session = useSession();
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <Layout className="public-shell">
      <FeishuAutoLogin
        sessionReady={session.isSuccess && !session.isFetching}
        authenticated={session.data?.authenticated === true}
      />
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <Layout.Header className="site-header">
        <Link className="brand" to="/">
          <BrandMark />
          <Typography.Title heading={5}>Fuma</Typography.Title>
          <Typography.Text type="tertiary" className="workspace-label">
            应用下载
          </Typography.Text>
        </Link>
        <nav aria-label="主要" className="public-desktop-nav">
          <Space spacing={16}>
            <Link to="/releases">已发布版本</Link>
            <Link to="/admin">管理入口</Link>
            {session.data?.authenticated && (
              <>
                <Avatar size="small" className="public-account-avatar">
                  {session.data.user?.display_name?.[0]}
                </Avatar>
                <span className="public-account-name">
                  {session.data.user?.display_name}
                </span>
                <LogoutButton compact />
              </>
            )}
          </Space>
        </nav>
        <Button
          type="button"
          className="public-menu-button"
          aria-label="打开导航与账号"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(true)}
        >
          <Icon name="tasks" />
        </Button>
      </Layout.Header>
      <SideSheet
        title="导航与账号"
        visible={menuOpen}
        onCancel={() => setMenuOpen(false)}
        width="min(320px, 100vw)"
        placement="right"
      >
        <nav className="public-mobile-nav" aria-label="手机导航">
          {session.data?.authenticated && (
            <div className="public-mobile-account">
              <Avatar>{session.data.user?.display_name?.[0]}</Avatar>
              <strong>{session.data.user?.display_name}</strong>
            </div>
          )}
          <Link to="/" onClick={() => setMenuOpen(false)}>
            <Icon name="apps" />
            应用下载
          </Link>
          <Link to="/releases" onClick={() => setMenuOpen(false)}>
            <Icon name="package" />
            已发布版本
          </Link>
          <Link to="/admin" onClick={() => setMenuOpen(false)}>
            <Icon name="grid" />
            管理入口
          </Link>
          {session.data?.authenticated && (
            <LogoutButton onLogout={() => setMenuOpen(false)} />
          )}
        </nav>
      </SideSheet>
      <Layout.Content tagName="div">
        <main id="main" tabIndex={-1}>
          <Outlet />
        </main>
      </Layout.Content>
      <Layout.Footer className="app-footer">
        Fuma · 移动端安装包管理
      </Layout.Footer>
    </Layout>
  );
}
