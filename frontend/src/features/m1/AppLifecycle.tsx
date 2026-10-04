import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { Button, Panel, Notice } from "../../shared/ui/controls";
import { ErrorBox, Loading, date, useCommand } from "../../shared/ui/common";

export function AppLifecycle({ app }: { app: DTO<"App"> }) {
  const [showImpact, setShowImpact] = useState(false);
  const cmd = useCommand();
  const client = useQueryClient();
  const impact = useQuery({
    queryKey: ["app-archive-impact", app.id, app.revision],
    queryFn: () => read("/api/v1/apps/{id}/archive-impact", { id: app.id }),
    enabled: showImpact && !app.archived_at,
  });
  return (
    <Panel>
      <h2>归档与恢复</h2>
      {cmd.feedback}
      {app.archived_at ? (
        <>
          <Notice>
            应用已于 {date(app.archived_at)}{" "}
            归档。历史数据可查看；恢复后仍保持停用，历史包和自动规则不会重新开放。
          </Notice>
          <Button
            type="button"
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run(
                "app-restore",
                () =>
                  write("/api/v1/apps/{id}/restore", "post", undefined, {
                    id: app.id,
                    revision: app.revision,
                  }),
                (saved) => client.setQueryData(["app", app.id], saved),
                "应用已恢复，当前仍为停用状态。",
                `恢复「${app.name}」？恢复后仍需检查配置并手动启用。`,
              )
            }
          >
            恢复应用
          </Button>
        </>
      ) : (
        <>
          <p>
            归档保留历史包、配置和审计，关闭新导入和下载授权。请先停用已上架的包、Actions
            规则及自动导入，并处理未完成任务。
          </p>
          <Button
            type="button"
            disabled={impact.isFetching}
            onClick={() => {
              setShowImpact(true);
              if (showImpact) void impact.refetch();
            }}
          >
            检查归档影响
          </Button>
          {showImpact && (
            <>
              {impact.isPending && <Loading />}
              <ErrorBox error={impact.error} />
              {impact.data && (
                <>
                  <p>
                    历史 Debug 包 {impact.data.debug_entries} 个 · 启用{" "}
                    {impact.data.active_debug_entries} 个 · 未完成任务{" "}
                    {impact.data.active_tasks} 个 · 启用 Actions 规则{" "}
                    {impact.data.active_actions_rules} 条
                  </p>
                  {impact.data.blockers.length ? (
                    <ul>
                      {impact.data.blockers.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>
                      当前没有阻塞项。提交时会再次检查，避免并发操作遗漏依赖。
                    </p>
                  )}
                  <div className="toolbar">
                    <Link to={`/admin/apps/${app.id}/debug`}>
                      管理 Debug 包
                    </Link>
                    <Link to={`/admin/apps/${app.id}/actions`}>
                      管理 Actions 规则
                    </Link>
                    <Link to={`/admin/apps/${app.id}/releases`}>
                      管理自动导入
                    </Link>
                    <Link to="/admin/tasks">任务中心</Link>
                  </div>
                  <Button
                    type="button"
                    className="danger"
                    disabled={
                      cmd.pending ||
                      !impact.data.can_archive ||
                      impact.isFetching ||
                      !!impact.error
                    }
                    onClick={() =>
                      void cmd.run(
                        "app-archive",
                        () =>
                          write(
                            "/api/v1/apps/{id}/archive",
                            "post",
                            undefined,
                            { id: app.id, revision: impact.data!.revision },
                          ),
                        (saved) => client.setQueryData(["app", app.id], saved),
                        "应用已归档。",
                        `归档「${app.name}」？历史数据保留，恢复也不会自动重新开放下载。`,
                      )
                    }
                  >
                    归档应用
                  </Button>
                </>
              )}
            </>
          )}
        </>
      )}
    </Panel>
  );
}
