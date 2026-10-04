import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { read } from "../../shared/api/http";
import Avatar from "@douyinfe/semi-ui-19/lib/es/avatar";
import Breadcrumb from "@douyinfe/semi-ui-19/lib/es/breadcrumb";
import Button from "@douyinfe/semi-ui-19/lib/es/button";
import Layout from "@douyinfe/semi-ui-19/lib/es/layout";
import Nav from "@douyinfe/semi-ui-19/lib/es/navigation";
import SideSheet from "@douyinfe/semi-ui-19/lib/es/sideSheet";
import Space from "@douyinfe/semi-ui-19/lib/es/space";
import Typography from "@douyinfe/semi-ui-19/lib/es/typography";
import { Link, Outlet, useLocation, useMatch } from "react-router";
import { AdminGuard, LogoutButton } from "../../features/m1/Auth";
import { globalOnlyPath, isGlobalAdmin } from "../../features/m1/permissions";
import { useSession } from "../../shared/ui/common";
import { BrandMark, Icon, type IconName } from "../../shared/ui/Icon";

const groups: {
  title: string;
  items: { to: string; title: string; icon: IconName }[];
}[] = [
  {
    title: "工作空间",
    items: [
      { to: "/admin", title: "工作台", icon: "grid" },
      { to: "/admin/apps", title: "应用管理", icon: "apps" },
      { to: "/admin/tasks", title: "任务中心", icon: "tasks" },
      { to: "/admin/notifications", title: "通知记录", icon: "bell" },
    ],
  },
  {
    title: "集成",
    items: [
      { to: "/admin/connectors", title: "GitHub 连接", icon: "branch" },
      { to: "/admin/settings/feishu", title: "飞书与机器人", icon: "chat" },
    ],
  },
  {
    title: "管理",
    items: [
      { to: "/admin/settings/cache", title: "本地缓存", icon: "disk" },
      { to: "/admin/settings/storage", title: "对象存储", icon: "disk" },
      { to: "/admin/audit", title: "审计日志", icon: "history" },
      { to: "/admin/settings/members", title: "成员与角色", icon: "shield" },
      { to: "/admin/settings/account", title: "账号与会话", icon: "shield" },
    ],
  },
];
function AdminShell() {
  const session = useSession();
  const user = session.data?.user;
  const visibleGroups = groups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) => isGlobalAdmin(user) || !globalOnlyPath(item.to),
      ),
    }))
    .filter((group) => group.items.length > 0);
  const { pathname } = useLocation();
  const appMatch = useMatch("/admin/apps/:appId/*");
  const appId = appMatch?.params.appId;
  const app = useQuery({
    queryKey: ["app", appId],
    queryFn: () => read("/api/v1/apps/{id}", { id: appId! }),
    enabled: Boolean(appId),
  });
  const appSection = {
    packages: "安装包",
    versions: "版本发布",
    releases: "GitHub Releases",
    debug: "Debug 包",
    actions: "Actions 规则",
    events: "构建事件",
  }[appMatch?.params["*"] ?? ""];
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const current = visibleGroups
    .flatMap((group) => group.items)
    .find((item) =>
      item.to === "/admin"
        ? pathname === item.to
        : pathname.startsWith(item.to),
    );
  const navigation = (mobile = false) => (
    <Nav
      aria-label="管理导航"
      className="admin-nav"
      isCollapsed={!mobile && collapsed}
      defaultOpenKeys={visibleGroups.map((group) => group.title)}
      onCollapseChange={setCollapsed}
      selectedKeys={[current?.to ?? ""]}
      renderWrapper={({ itemElement, props }) =>
        typeof props.itemKey === "string" && props.itemKey.startsWith("/") ? (
          <Link to={props.itemKey} onClick={() => setMobileOpen(false)}>
            {itemElement}
          </Link>
        ) : (
          itemElement
        )
      }
    >
      {visibleGroups.map((group) => (
        <Nav.Sub key={group.title} itemKey={group.title} text={group.title}>
          {group.items.map((item) => (
            <Nav.Item
              key={item.to}
              itemKey={item.to}
              text={item.title}
              icon={<Icon name={item.icon} />}
            />
          ))}
        </Nav.Sub>
      ))}
      {!mobile && <Nav.Footer collapseButton />}
    </Nav>
  );
  return (
    <>
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <Layout className="admin-shell">
        <Layout.Header className="admin-header">
          <Space spacing={16}>
            <Button
              className="mobile-navigation"
              theme="borderless"
              type="tertiary"
              icon={<Icon name="sidebar" />}
              aria-label="打开管理导航"
              onClick={() => setMobileOpen(true)}
            />
            <Link className="brand" to="/admin">
              <BrandMark />
              <Typography.Title heading={5}>Fuma</Typography.Title>
            </Link>
            <Typography.Text className="workspace-label" type="tertiary">
              应用分发控制台
            </Typography.Text>
          </Space>
          <Space spacing={16}>
            <Link className="portal-link" to="/">
              下载门户 <Icon name="external" size={14} />
            </Link>
            <Link
              className="account-link"
              to="/admin/settings/account"
              aria-label={`${user?.display_name ?? "当前用户"} 账号与会话`}
            >
              <Avatar size="small" color="blue">
                {user?.display_name?.[0] ?? "?"}
              </Avatar>
              <span>{user?.display_name}</span>
            </Link>
            <LogoutButton compact />
          </Space>
        </Layout.Header>
        <Layout className="admin-body">
          <Layout.Sider
            className="admin-sider"
            style={{ width: collapsed ? 60 : 224 }}
          >
            {navigation()}
          </Layout.Sider>
          <Layout.Content className="admin-content" tagName="div">
            <Breadcrumb className="workspace-breadcrumb">
              <Breadcrumb.Item>
                <Link to="/admin">控制台</Link>
              </Breadcrumb.Item>
              {appId ? (
                [
                  <Breadcrumb.Item key="apps">
                    <Link to="/admin/apps">应用管理</Link>
                  </Breadcrumb.Item>,
                  <Breadcrumb.Item key="app">
                    <Link to={`/admin/apps/${appId}`}>
                      {app.data?.name ?? "应用详情"}
                    </Link>
                  </Breadcrumb.Item>,
                  <Breadcrumb.Item key="section">
                    {appSection ?? "应用设置"}
                  </Breadcrumb.Item>,
                ]
              ) : (
                <Breadcrumb.Item>
                  {current?.title ?? "应用详情"}
                </Breadcrumb.Item>
              )}
            </Breadcrumb>
            <main id="main" tabIndex={-1}>
              <Outlet />
            </main>
            <Layout.Footer className="app-footer">
              Fuma · 移动端安装包管理
            </Layout.Footer>
          </Layout.Content>
        </Layout>
      </Layout>
      <SideSheet
        visible={mobileOpen}
        onCancel={() => setMobileOpen(false)}
        title="管理导航"
        placement="left"
        width={280}
      >
        {navigation(true)}
      </SideSheet>
    </>
  );
}
export function Component() {
  return (
    <AdminGuard>
      <AdminShell />
    </AdminGuard>
  );
}
