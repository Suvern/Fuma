import Card from "@douyinfe/semi-ui-19/lib/es/card";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { read, type DTO } from "../../../shared/api/http";
import {
  Empty,
  ErrorBox,
  Loading,
  Status,
  date,
  labels,
} from "../../../shared/ui/common";

function TaskRow({ task }: { task: DTO<"Task"> }) {
  return (
    <Link className="dashboard-row" to={`/admin/tasks/${task.id}`}>
      <span className="row-copy">
        <strong>{labels[task.kind] ?? task.kind}</strong>
        <small>
          {task.app_name ?? "系统维护"}
          {task.resource_name ? ` · ${task.resource_name}` : ""}
        </small>
        <small>{task.result_summary ?? date(task.updated_at)}</small>
      </span>
      <Status value={task.state} />
    </Link>
  );
}

export function TaskOverview() {
  const recent = useQuery({
    queryKey: ["dashboard-business-tasks"],
    queryFn: () =>
      read("/api/v1/tasks", {
        query: { category: "business", page: 1, page_size: 4 },
      }),
    refetchInterval: 10000,
  });
  const failed = useQuery({
    queryKey: ["dashboard-failed-tasks"],
    queryFn: () =>
      read("/api/v1/tasks", {
        query: { category: "all", state: "failed", page: 1, page_size: 3 },
      }),
    refetchInterval: 10000,
  });
  return (
    <Card
      className="panel"
      title="业务任务"
      headerExtraContent={
        <Link aria-label="查看全部任务" to="/admin/tasks?category=all">
          查看全部
        </Link>
      }
    >
      <ErrorBox error={recent.error || failed.error} />
      {recent.isPending && <Loading />}
      {!!failed.data?.items.length && (
        <>
          <h3>失败待排查</h3>
          {failed.data.items.map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
          <Link to="/admin/tasks?category=all&state=failed">
            查看所有失败任务
          </Link>
          <h3>最近业务任务</h3>
        </>
      )}
      {recent.data?.items.map((task) => (
        <TaskRow key={task.id} task={task} />
      ))}
      {recent.data?.total === 0 && (
        <Empty>暂无业务任务。上传、构建和发布后可在这里跟踪结果。</Empty>
      )}
      <p>
        <Link to="/admin/tasks?category=system">查看例行同步与系统维护</Link>
      </p>
    </Card>
  );
}
