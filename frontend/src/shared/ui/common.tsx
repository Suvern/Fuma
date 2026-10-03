import type { CheckboxProps } from "@douyinfe/semi-ui-19/lib/es/checkbox";
import Checkbox from "@douyinfe/semi-ui-19/lib/es/checkbox";
import SemiEmpty from "@douyinfe/semi-ui-19/lib/es/empty";
import Pagination from "@douyinfe/semi-ui-19/lib/es/pagination";
import Spin from "@douyinfe/semi-ui-19/lib/es/spin";
import Tag from "@douyinfe/semi-ui-19/lib/es/tag";
import { Notice, Input, Button } from "./controls";
/* eslint-disable react-refresh/only-export-components -- Shared page primitives and hooks intentionally form one module. */
import {
  useId,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { ApiError, read, ssoUrl, type DTO } from "../api/http";
import { PageTitle } from "../components/PageTitle";
import { Icon, type IconName } from "./Icon";

export const labels: Record<string, string> = {
  ready: "已就绪",
  missing: "未缓存",
  queued: "排队中",
  downloading: "下载中",
  verifying: "校验中",
  failed: "失败",
  evicted: "已清理",
  running: "执行中",
  succeeded: "成功",
  partial_success: "部分成功",
  unknown: "结果未知",
  waiting_run: "等待构建结束",
  caching: "缓存中",
  notifying: "通知中",
  received: "已接收",
  sending: "发送中",
  android: "Android",
  ios: "iOS",
  pass: "通过",
  fail: "未通过",
  ok: "正常",
  unavailable: "不可用",
  untested: "未测试",
  unverified: "未验证",
  joined: "已入群",
  removed: "已退群",
  available: "可发送",
  never: "尚未同步",
  syncing: "同步中",
  verify: "核验来源",
  wait_run: "等待构建",
  cache: "缓存文件",
  notify: "发送通知",
  success: "成功",
  failure: "失败",
  partial_failure: "部分失败",
  release_sync: "Release 同步",
  chat_sync: "群聊同步",
  cache_download: "缓存下载",
  build_event: "构建事件",
  notification: "通知发送",
  cache_cleanup: "缓存清理",
  done: "完成",
  pending: "待处理",
};
export function Status({ value }: { value: string }) {
  const color = [
    "ready",
    "succeeded",
    "pass",
    "ok",
    "success",
    "available",
    "joined",
    "done",
  ].includes(value)
    ? "green"
    : ["failed", "fail", "failure", "unavailable", "removed"].includes(value)
      ? "red"
      : [
            "unknown",
            "partial_success",
            "partial_failure",
            "unverified",
          ].includes(value)
        ? "orange"
        : [
              "running",
              "queued",
              "downloading",
              "verifying",
              "syncing",
              "caching",
              "sending",
              "notifying",
            ].includes(value)
          ? "blue"
          : "grey";
  return (
    <Tag color={color} shape="square">
      {labels[value] ?? value}
    </Tag>
  );
}
export function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
export function date(value?: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "—";
}
export function Title({
  children,
  description,
  actions,
}: {
  children: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <PageTitle title={children}>{children}</PageTitle>
          {description && <p className="muted">{description}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
    </>
  );
}
const fieldHints: Record<string, string> = {
  name: "请填写名称，且不要超过 100 个字符。",
  public_slug:
    "分发标识须为 3–64 位小写字母、数字或连字符，首尾须为字母或数字。",
  description: "描述不能超过 2000 个字符。",
  platforms: "请至少选择一个支持平台。",
  full_name: "请按 owner/repository 格式填写仓库完整名称。",
  workflow_path:
    "Workflow 路径须以 .github/workflows/ 开头，并以 .yml 或 .yaml 结尾。",
};
export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Notice role="alert" className="notice error">
      <strong>
        {error instanceof Error ? error.message : "请求失败，请稍后重试。"}
      </strong>
      {error instanceof ApiError && (
        <>
          <p>
            {error.detail.code}
            {error.requestId && ` · 请求 ${error.requestId}`}
          </p>
          {error.detail.field_errors?.map((x) => (
            <p key={x.field}>
              {fieldHints[x.field.replace(/^body\./, "").split(".")[0] ?? ""] ??
                `请检查输入内容：${x.message}`}
            </p>
          ))}
          {error.status === 412 && (
            <p>数据已被修改，请刷新页面，核对最新内容后再提交。</p>
          )}
          {[401, 403].includes(error.status) &&
            !error.detail.code.startsWith("GITHUB_") && (
              <p>
                <Link to="/login">重新登录</Link>，或{" "}
                <a href={ssoUrl()}>重新验证飞书资格</a>。
              </p>
            )}
        </>
      )}
    </Notice>
  );
}
export function Loading() {
  return (
    <div role="status" className="loading-state">
      <Spin />
      <span>正在加载…</span>
    </div>
  );
}
export function Empty({
  children = "暂无数据",
  title,
  icon = "package",
  action,
}: {
  children?: ReactNode;
  title?: string;
  icon?: IconName;
  action?: ReactNode;
}) {
  return (
    <SemiEmpty
      className="empty-state"
      image={<Icon name={icon} size={48} />}
      title={title}
      description={children}
    >
      {action}
    </SemiEmpty>
  );
}
export function Field({
  label,
  help,
  validationMessage,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  help?: string;
  validationMessage?: string;
}) {
  const uniqueId = useId();
  const id = props.id ?? uniqueId;
  const [error, setError] = useState("");
  return (
    <div className="field">
      <label htmlFor={id}>
        {label}
        {props.required && " *"}
      </label>
      <Input
        {...props}
        id={id}
        aria-invalid={!!error || undefined}
        aria-describedby={
          [help && `${id}-help`, error && `${id}-error`]
            .filter(Boolean)
            .join(" ") || undefined
        }
        onInvalid={(event) => {
          setError(
            event.currentTarget.validity.patternMismatch && validationMessage
              ? validationMessage
              : event.currentTarget.validationMessage,
          );
          props.onInvalid?.(event);
        }}
        onInput={(event) => {
          if (event.currentTarget.validity.valid) setError("");
          props.onInput?.(event);
        }}
      />
      {help && <small id={`${id}-help`}>{help}</small>}
      {error && (
        <small id={`${id}-error`} role="alert" className="field-error">
          {error}
        </small>
      )}
    </div>
  );
}
export function Check({
  label,
  ...props
}: CheckboxProps & { label: string; name?: string }) {
  return <Checkbox {...props}>{label}</Checkbox>;
}
export function Form({
  children,
  submit,
  action = "#",
  className = "",
}: {
  children: ReactNode;
  submit: (data: FormData) => void;
  action?: string;
  className?: string;
}) {
  return (
    <form
      action={action}
      method="post"
      className={`form ${className}`}
      onSubmit={(e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        submit(new FormData(e.currentTarget));
      }}
    >
      {children}
    </form>
  );
}
export const text = (f: FormData, name: string) =>
  String(f.get(name) ?? "").trim();
export const lines = (f: FormData, name: string) =>
  text(f, name)
    .split(/[\n,]+/)
    .map((x) => x.trim())
    .filter(Boolean);
export function useCommand() {
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");
  const keys = useRef(new Map<string, string>());
  const lock = useRef(false);
  async function run<T>(
    intent: string,
    execute: (key: string) => Promise<T>,
    success?: (result: T) => void,
    successMessage = "请求已提交。",
  ) {
    if (lock.current) return;
    lock.current = true;
    setPending(true);
    setError(undefined);
    setMessage("");
    const key = keys.current.get(intent) ?? crypto.randomUUID();
    keys.current.set(intent, key);
    try {
      const result = await execute(key);
      keys.current.delete(intent);
      success?.(result);
      setMessage(successMessage);
      await client.invalidateQueries();
    } catch (e) {
      setError(e);
    } finally {
      lock.current = false;
      setPending(false);
    }
  }
  return {
    run,
    pending,
    feedback: (
      <>
        <ErrorBox error={error} />
        {message && (
          <Notice role="status" className="notice success">
            {message}
          </Notice>
        )}
      </>
    ),
  };
}
export function Pager({
  data,
  page,
  setPage,
}: {
  data?: { total: number; page_size: number };
  page: number;
  setPage: (p: number) => void;
}) {
  if (!data || data.total === 0) return null;
  return (
    <nav className="pager" aria-label="分页">
      <Pagination
        total={data.total}
        pageSize={data.page_size}
        currentPage={page}
        onPageChange={setPage}
        showTotal
        showSizeChanger={false}
      />
    </nav>
  );
}
export function useFilters() {
  const searchId = useId();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  return {
    page,
    setPage,
    q,
    search: (
      <form
        role="search"
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(text(new FormData(e.currentTarget), "q"));
          setPage(1);
        }}
      >
        <label className="sr-only" htmlFor={searchId}>
          关键词
        </label>
        <div className="search-input">
          <Icon name="search" size={17} />
          <Input
            type="search"
            id={searchId}
            name="q"
            placeholder="搜索名称、版本或文件…"
          />
        </div>
        <Button>搜索</Button>
      </form>
    ),
  };
}
export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: ({ signal }) => read("/api/v1/auth/browser-context", { signal }),
    staleTime: 0,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
}
export function Checks({ checks }: { checks: DTO<"Check">[] }) {
  return (
    <ul className="checks">
      {checks.map((x) => (
        <li key={x.code}>
          <Status value={x.status} /> <span>{x.message}</span>
        </li>
      ))}
    </ul>
  );
}
export function TaskNotice({ task }: { task?: DTO<"TaskAccepted"> }) {
  const client = useQueryClient();
  const taskId = task?.task_id;
  const query = useQuery({
    queryKey: ["accepted-task", taskId],
    queryFn: () => read("/api/v1/tasks/{id}", { id: taskId }),
    enabled: Boolean(taskId),
    refetchInterval: (state) =>
      state.state.error ||
      ["succeeded", "partial_success", "failed", "unknown"].includes(
        state.state.data?.state ?? "",
      )
        ? false
        : 1000,
  });
  const settled = Boolean(
    query.data &&
    ["succeeded", "partial_success", "failed", "unknown"].includes(
      query.data.state,
    ),
  );
  useEffect(() => {
    if (settled) {
      // A 202 response can precede the worker setting the resource's sync_state.
      // Follow the durable task, then refresh the resulting resource snapshot.
      void client.invalidateQueries({
        predicate: (query) => query.queryKey[0] !== "accepted-task",
      });
    }
  }, [client, settled, taskId]);
  if (!task) return null;
  return (
    <>
      <Notice role="status" className="notice">
        {query.data ? (
          <>
            任务：
            <Status value={query.data.state} />
          </>
        ) : (
          "任务已受理。"
        )}{" "}
        <Link to={`/admin/tasks/${task.task_id}`}>查看任务进度</Link>
      </Notice>
      <ErrorBox error={query.error} />
    </>
  );
}
export function JsonDetails({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}
