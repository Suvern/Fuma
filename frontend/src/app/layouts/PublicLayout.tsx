import Avatar from "@douyinfe/semi-ui-19/lib/es/avatar";
import Layout from "@douyinfe/semi-ui-19/lib/es/layout";
import Space from "@douyinfe/semi-ui-19/lib/es/space";
import Typography from "@douyinfe/semi-ui-19/lib/es/typography";
import { Link, Outlet } from "react-router";
import { LogoutButton } from "../../features/m1/Auth";
import { FeishuAutoLogin } from "../../features/m1/FeishuAutoLogin";
import { useSession } from "../../shared/ui/common";
import { BrandMark } from "../../shared/ui/Icon";
export function PublicLayout() {
  const session = useSession();
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
        <nav aria-label="主要">
          <Space spacing={16}>
            <Link to="/releases">已发布版本</Link>
            <Link to="/admin">管理入口</Link>
            {session.data?.authenticated && (
              <>
                <Avatar size="small" className="public-account-avatar">
                  {session.data.user?.display_name?.[0]}
                </Avatar>
                <span className="public-account-name">{session.data.user?.display_name}</span>
                <LogoutButton compact />
              </>
            )}
          </Space>
        </nav>
      </Layout.Header>
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
