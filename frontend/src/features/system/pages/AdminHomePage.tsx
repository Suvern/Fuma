import { Metric } from "../../../shared/ui/controls";
import Banner from "@douyinfe/semi-ui-19/lib/es/banner";
import Button from "@douyinfe/semi-ui-19/lib/es/button";
import Card from "@douyinfe/semi-ui-19/lib/es/card";
import Descriptions from "@douyinfe/semi-ui-19/lib/es/descriptions";
import Space from "@douyinfe/semi-ui-19/lib/es/space";
import Steps from "@douyinfe/semi-ui-19/lib/es/steps";
import Typography from "@douyinfe/semi-ui-19/lib/es/typography";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { read } from "../../../shared/api/http";
import {
  Empty,
  ErrorBox,
  Loading,
  Status,
  Title,
  date,
  labels,
  size,
  useSession,
} from "../../../shared/ui/common";
import { Icon } from "../../../shared/ui/Icon";
import { isGlobalAdmin } from "../../m1/permissions";

const services = [
  ["api", "API 服务"],
  ["database", "数据库"],
  ["redis", "消息队列"],
  ["worker", "任务执行"],
  ["scheduler", "任务调度"],
] as const;

export function Component() {
  const session = useSession();
  if (session.isPending) return <Loading />;
  return isGlobalAdmin(session.data?.user) ? (
    <AdminDashboard />
  ) : (
    <MaintainerDashboard />
  );
}

function MaintainerDashboard() {
  const apps = useQuery({
    queryKey: ["maintainer-apps"],
    queryFn: () => read("/api/v1/apps", { query: { page: 1, page_size: 8 } }),
  });
  const tasks = useQuery({
    queryKey: ["maintainer-tasks"],
    queryFn: () => read("/api/v1/tasks", { query: { page: 1, page_size: 8 } }),
    refetchInterval: 10000,
  });
  return (
    <>
      <Title description="管理获授权应用的安装包、版本发布和任务。全局连接、存储及成员授权由管理员维护。">
        我的工作台
      </Title>
      <div className="dashboard-columns">
        <Card
          className="panel"
          title="我的应用"
          headerExtraContent={<Link to="/admin/apps">查看全部</Link>}
        >
          <ErrorBox error={apps.error} />
          {apps.isPending && <Loading />}
          {apps.data?.items.map((app) => (
            <Link
              className="dashboard-row"
              key={app.id}
              to={`/admin/apps/${app.id}`}
            >
              <strong>{app.name}</strong>
              <span>
                {app.package_count ?? 0} 个正式包 · {app.publication_count ?? 0}{" "}
                个发布
              </span>
            </Link>
          ))}
          {apps.data?.total === 0 && (
            <Empty>尚未获得应用授权，请联系管理员分配。</Empty>
          )}
        </Card>
        <Card
          className="panel"
          title="应用最近任务"
          headerExtraContent={<Link to="/admin/tasks">查看全部</Link>}
        >
          <ErrorBox error={tasks.error} />
          {tasks.isPending && <Loading />}
          {tasks.data?.items.map((task) => (
            <Link
              className="dashboard-row"
              key={task.id}
              to={`/admin/tasks/${task.id}`}
            >
              <strong>{labels[task.kind] ?? task.kind}</strong>
              <Status value={task.state} />
            </Link>
          ))}
          {tasks.data?.total === 0 && <Empty>获授权应用暂无任务。</Empty>}
        </Card>
      </div>
    </>
  );
}

function AdminDashboard() {
  const health = useQuery({
    queryKey: ["system-health"],
    queryFn: () => read("/api/v1/system/health"),
    refetchInterval: 10000,
  });
  const apps = useQuery({
    queryKey: ["dashboard-apps"],
    queryFn: () => read("/api/v1/apps", { query: { page: 1, page_size: 4 } }),
  });
  const tasks = useQuery({
    queryKey: ["dashboard-tasks"],
    queryFn: () => read("/api/v1/tasks", { query: { page: 1, page_size: 4 } }),
    refetchInterval: 10000,
  });
  const connectors = useQuery({
    queryKey: ["dashboard-connectors"],
    queryFn: () => read("/api/v1/connectors/github", { query: { page: 1 } }),
  });
  const feishu = useQuery({
    queryKey: ["feishu"],
    queryFn: () => read("/api/v1/settings/feishu"),
  });
  const steps: {
    title: string;
    description: string;
    to: string;
    done: boolean | undefined;
  }[] = [
    {
      title: "创建你的应用",
      description: "添加 Android 或 iOS 应用",
      to: "/admin/apps?new=1",
      done: apps.data ? apps.data.total > 0 : undefined,
    },
    {
      title: "添加 GitHub 连接",
      description: "保存仓库访问凭据",
      to: "/admin/connectors",
      done: connectors.data ? connectors.data.total > 0 : undefined,
    },
    {
      title: "验证飞书登录",
      description: "确认租户身份，开放团队访问",
      to: "/admin/settings/feishu",
      done: feishu.data
        ? feishu.data.verified && feishu.data.enabled
        : undefined,
    },
  ];
  const complete = steps.filter((step) => step.done).length;
  const setupKnown = steps.every((step) => step.done !== undefined);
  const healthy =
    health.data && services.every(([key]) => health.data[key] === "ok");
  return (
    <>
      <Title
        description="查看应用、分发任务与服务运行状态。"
        actions={
          <Link className="button primary" to="/admin/apps?new=1">
            <Icon name="plus" size={16} />
            新建应用
          </Link>
        }
      >
        工作台
      </Title>
      <div className="stat-grid">
        <Card>
          <Metric
            title="应用总数"
            value={apps.data?.total ?? "—"}
            suffix="个"
          />
        </Card>
        <Card>
          <Metric
            title="GitHub 连接"
            value={connectors.data?.total ?? "—"}
            suffix="个"
          />
        </Card>
        <Card>
          <Metric
            title="磁盘可用空间"
            value={health.data ? size(health.data.cache_free_bytes) : "—"}
          />
        </Card>
        <Card>
          <Metric
            title="飞书接入"
            value={
              feishu.data
                ? feishu.data.verified && feishu.data.enabled
                  ? "已就绪"
                  : "待配置"
                : "—"
            }
          />
        </Card>
      </div>
      <ErrorBox error={health.error} />
      <Card
        className="panel"
        title="服务运行状态"
        headerExtraContent={
          <Button
            icon={<Icon name="refresh" size={16} />}
            theme="borderless"
            aria-label="刷新服务状态"
            loading={health.isFetching}
            onClick={() => void health.refetch()}
          >
            刷新
          </Button>
        }
      >
        <Banner
          fullMode={false}
          type={healthy ? "success" : health.error ? "danger" : "info"}
          closeIcon={null}
          description={
            health.isPending
              ? "正在连接服务"
              : health.error
                ? "服务状态暂不可用"
                : healthy
                  ? "所有服务运行正常"
                  : "部分服务需要关注"
          }
        />
        <div className="status-list" style={{ marginTop: 20 }}>
          {services.map(([key, label]) => (
            <span key={key}>
              {label}
              <Status value={health.data?.[key] ?? "pending"} />
            </span>
          ))}
        </div>
      </Card>
      {(!setupKnown || complete < steps.length) && (
        <Card
          className="panel"
          title="接入指引"
          headerExtraContent={
            <Typography.Text type="tertiary">
              {setupKnown ? `${complete} / 3 已完成` : "正在检查"}
            </Typography.Text>
          }
        >
          <ErrorBox error={apps.error || connectors.error || feishu.error} />
          <Steps
            className="setup-steps"
            type="basic"
            current={steps.findIndex((step) => !step.done)}
          >
            {steps.map((step) => (
              <Steps.Step
                key={step.title}
                title={<Link to={step.to}>{step.title}</Link>}
                description={step.description}
                status={step.done ? "finish" : "wait"}
              />
            ))}
          </Steps>
        </Card>
      )}
      <div className="dashboard-columns">
        <Card
          className="panel"
          title="我的应用"
          headerExtraContent={
            <Link aria-label="查看全部应用" to="/admin/apps">
              查看全部
            </Link>
          }
        >
          <ErrorBox error={apps.error} />
          {apps.isPending && <Loading />}
          {apps.data?.total === 0 && (
            <Empty
              title="尚未添加应用"
              action={
                <Link className="button primary" to="/admin/apps?new=1">
                  新建应用
                </Link>
              }
            >
              添加应用并关联仓库，开始分发安装包。
            </Empty>
          )}
          {apps.data?.items.map((app) => (
            <Link
              className="dashboard-row"
              to={`/admin/apps/${app.id}`}
              key={app.id}
            >
              <span className="app-monogram">{app.name[0]}</span>
              <span className="row-copy">
                <strong>{app.name}</strong>
                <small>
                  {app.repository?.full_name ?? "待绑定 GitHub 仓库"}
                </small>
              </span>
              <Typography.Text type="tertiary">
                {app.debug_entry_count} 个包
              </Typography.Text>
              <Icon name="chevron" size={14} />
            </Link>
          ))}
        </Card>
        <Card
          className="panel"
          title="最近任务"
          headerExtraContent={
            <Link aria-label="查看全部任务" to="/admin/tasks">
              查看全部
            </Link>
          }
        >
          <ErrorBox error={tasks.error} />
          {tasks.isPending && <Loading />}
          {tasks.data?.total === 0 && (
            <Empty icon="tasks">任务执行后，进度与结果会显示在这里。</Empty>
          )}
          {tasks.data?.items.map((task) => (
            <Link
              className="dashboard-row"
              key={task.id}
              to={`/admin/tasks/${task.id}`}
            >
              <Icon name="tasks" size={20} />
              <span className="row-copy">
                <strong>{labels[task.kind] ?? task.kind}</strong>
                <small>{date(task.created_at)}</small>
              </span>
              <Status value={task.state} />
            </Link>
          ))}
        </Card>
      </div>
      <Card
        className="panel"
        title="运行环境"
        headerExtraContent={<Link to="/admin/settings/cache">缓存设置</Link>}
      >
        {health.isPending && <Loading />}
        {health.data && (
          <Descriptions
            align="left"
            row
            data={[
              {
                key: "下载门户",
                value: (
                  <Typography.Text copyable>
                    {health.data.public_origin}
                  </Typography.Text>
                ),
              },
              {
                key: "缓存目录",
                value: health.data.cache_writable ? "可读写" : "不可写",
              },
              {
                key: "最近任务心跳",
                value: date(health.data.worker_last_seen_at),
              },
            ]}
          />
        )}
        {health.error && (
          <Space>
            <Typography.Text type="tertiary">
              暂时无法读取运行环境，请刷新服务状态重试。
            </Typography.Text>
          </Space>
        )}
      </Card>
    </>
  );
}
