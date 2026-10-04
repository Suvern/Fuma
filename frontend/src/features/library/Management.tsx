import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { Button } from "../../shared/ui/controls";
import { ErrorBox, Form, date, text, useCommand } from "../../shared/ui/common";

export function PackageManagement({
  package: p,
}: {
  package: DTO<"PackageInfo">;
}) {
  const [expanded, setExpanded] = useState(false);
  const [task, setTask] = useState<DTO<"TaskAccepted">>();
  const cmd = useCommand();
  const impact = useQuery({
    queryKey: ["package-delete-impact", p.id, p.revision],
    queryFn: () => read("/api/v1/packages/{id}/deletion-impact", { id: p.id }),
    enabled: expanded,
  });
  return (
    <details onToggle={(e) => setExpanded(e.currentTarget.open)}>
      <summary>内部备注与删除检查</summary>
      {cmd.feedback}
      <Form
        key={p.revision}
        submit={(form) =>
          void cmd.run("notes", () =>
            write(
              "/api/v1/packages/{id}",
              "patch",
              { internal_notes: text(form, "internal_notes") },
              { id: p.id, revision: p.revision },
            ),
          )
        }
      >
        <label>
          内部备注（下载页不可见）
          <textarea
            name="internal_notes"
            defaultValue={p.internal_notes}
            maxLength={2000}
          />
        </label>
        <Button disabled={cmd.pending || p.state === "deleted"}>
          保存备注
        </Button>
      </Form>
      <ErrorBox error={impact.error} />
      {impact.data && (
        <>
          <p>
            至少保留至 {date(impact.data.retained_until)}
            。有发布、历史发布或旧页面引用时不能删除。
          </p>
          {impact.data.blockers.map((b) => (
            <p key={b}>{b}</p>
          ))}
          <Button
            disabled={cmd.pending || !impact.data.can_delete}
            onClick={() =>
              void cmd.run(
                "delete-package",
                () =>
                  write("/api/v1/packages/{id}", "delete", undefined, {
                    id: p.id,
                    revision: p.revision,
                  }),
                setTask,
                "清理任务已创建。",
                `确认删除 ${p.file_name} 的文件？元数据保留供审计，物理文件清理后不能恢复。`,
              )
            }
          >
            删除文件
          </Button>
        </>
      )}
      {task && (
        <Link to={`/admin/tasks/${task.task_id}`}>查看文件清理任务</Link>
      )}
    </details>
  );
}

export function DefaultReleaseControl({
  publication: p,
}: {
  publication: DTO<"PublicationInfo">;
}) {
  const cmd = useCommand();
  const query = useQuery({
    queryKey: ["release-default", p.app_id, p.platform],
    queryFn: () =>
      read("/api/v1/apps/{id}/release-defaults/{platform}", {
        id: p.app_id,
        platform: p.platform,
      }),
    enabled: p.mode === "release" && p.state === "published",
  });
  if (p.mode !== "release" || p.state !== "published") return null;
  const selected = query.data?.publication_id === p.id;
  return (
    <div>
      {cmd.feedback}
      <ErrorBox error={query.error} />
      <p>
        {selected
          ? "此为本平台默认展示版本。"
          : "默认展示需要显式选择；不会根据版本名称或时间自动切换。"}
      </p>
      <Button
        disabled={cmd.pending || !query.data}
        onClick={() =>
          void cmd.run(
            "set-default",
            () =>
              write(
                "/api/v1/apps/{id}/release-defaults/{platform}",
                "put",
                { publication_id: selected ? null : p.id },
                {
                  id: p.app_id,
                  platform: p.platform,
                  revision: query.data!.revision,
                },
              ),
            undefined,
            "默认展示已更新。",
            `${selected ? "取消" : "设置"} ${p.platform} 默认展示版本？仅改变展示顺序，不改变文件权限。`,
          )
        }
      >
        {selected ? "取消默认展示" : "设为默认展示"}
      </Button>
    </div>
  );
}
