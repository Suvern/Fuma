// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { CatalogEntryPage } from "./Debug";
import { NotificationPage } from "./Operations";
import { LoginPage } from "./Auth";
import { ReleasesPage } from "./GitHub";
import { useCommand } from "../../shared/ui/common";
vi.mock("../../shared/api/http", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
const client = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
let queryClient: QueryClient;
function mount(
  element: React.ReactNode,
  path = "/debug/entry",
  route = "/debug/:id",
) {
  queryClient = client();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={element} />
          <Route path="/admin" element={<p>已进入后台</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const session = {
  authenticated: true,
  viewer_key: "feishu-viewer",
  csrf_token: "csrf",
  user: {
    id: "user",
    kind: "feishu",
    role: "downloader",
    display_name: "测试用户",
    tenant_key: "tenant",
    must_change_password: false,
  },
};
const cache = {
  state: "missing",
  downloaded_bytes: 0,
  total_bytes: 1024,
  sha256: null,
  error_code: null,
  error_message: null,
  updated_at: null,
};
const entry = {
  id: "entry",
  app: {
    id: "app",
    name: "Demo App",
    public_slug: "demo",
    description: "",
    platforms: ["android"],
    debug_entry_count: 1,
  },
  mode: "debug",
  platform: "android",
  file_name: "demo.apk",
  size_bytes: 1024,
  version_name: null,
  build_number: null,
  version_label: "v1.0",
  version_label_source: "tag",
  created_at: "2026-10-01T00:00:00Z",
  cache,
  page_url: "http://localhost/debug/entry",
  installation_notice: null,
};
const prep = {
  entry_id: "entry",
  state: "ready",
  downloaded_bytes: 1024,
  total_bytes: 1024,
  retry_after_seconds: 1,
  error_code: null,
  error_message: null,
};
beforeEach(() => vi.resetAllMocks());
afterEach(() => {
  cleanup();
  queryClient?.clear();
});
function downloadReads() {
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/auth/browser-context") return session as never;
    if (path === "/api/v1/auth/bootstrap-status")
      return { initialized: true, sso_enabled: true } as never;
    if (path === "/api/v1/catalog/debug-entries/{id}") return entry as never;
    if (path === "/api/v1/catalog/debug-entries/{id}/preparation")
      return prep as never;
    throw Error("unexpected read");
  });
}
describe("M1 页面关键流程", () => {
  it("首次绑定失败可返回接入设置，不依赖尚未启用的普通SSO", async () => {
    vi.mocked(read).mockResolvedValue({
      initialized: true,
      sso_enabled: false,
    } as never);
    mount(
      <LoginPage />,
      "/login?error=AUTH_FAILED&return_to=%2Fadmin%2Fsettings%2Ffeishu",
      "/login",
    );
    const link = await screen.findByRole("link", { name: "返回接入设置" });
    expect(link.getAttribute("href")).toBe("/admin/settings/feishu");
    expect(screen.queryByRole("link", { name: "重新验证飞书资格" })).toBeNull();
  });
  it("普通飞书登录保留经过校验的下载详情回跳地址", async () => {
    vi.mocked(read).mockResolvedValue({
      initialized: true,
      sso_enabled: true,
    } as never);
    mount(<LoginPage />, "/login?return_to=%2Fdebug%2Fentry", "/login");
    const link = await screen.findByRole("link", {
      name: "使用飞书登录",
    });
    expect(link.getAttribute("href")).toBe(
      "/api/v1/auth/feishu/start?return_to=%2Fdebug%2Fentry",
    );
  });
  it("Release刷新在排队窗口仍追踪任务，终态刷新最新快照", async () => {
    let taskReads = 0;
    let completed = false;
    vi.mocked(read).mockImplementation(async (path) => {
      if (path === "/api/v1/tasks/{id}") {
        completed = ++taskReads > 1;
        return {
          id: "release-task",
          state: completed ? "succeeded" : "queued",
        } as never;
      }
      if (path === "/api/v1/apps/{id}/github/releases")
        return {
          items: completed
            ? [
                {
                  id: "release",
                  name: "异步同步后的版本",
                  tag_name: "v2",
                  body: "",
                  draft: false,
                  prerelease: false,
                  published_at: null,
                  assets: [],
                },
              ]
            : [],
          page: 1,
          page_size: 20,
          total: completed ? 1 : 0,
          synced_at: null,
          sync_state: completed ? "ready" : "never",
          sync_error_code: null,
        } as never;
      throw Error("unexpected read");
    });
    vi.mocked(write).mockResolvedValue({
      task_id: "release-task",
      status_url: "/api/v1/tasks/release-task",
    } as never);
    mount(
      <ReleasesPage />,
      "/admin/apps/app/releases",
      "/admin/apps/:id/releases",
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "同步 Releases" }),
    );
    expect(await screen.findByText("排队中")).toBeTruthy();
    await waitFor(
      () =>
        expect(
          screen.getByRole("heading", { name: "异步同步后的版本" }),
        ).toBeTruthy(),
      { timeout: 3000 },
    );
    expect(taskReads).toBe(2);
  });
  it("未启用 SSO 时说明接入状态，不给出无效登录入口", async () => {
    vi.mocked(read).mockImplementation(async (path) =>
      path === "/api/v1/auth/bootstrap-status"
        ? ({ initialized: true, sso_enabled: false } as never)
        : ({
            authenticated: false,
            viewer_key: "anonymous",
            csrf_token: "csrf",
            user: null,
          } as never),
    );
    mount(<CatalogEntryPage />);
    expect(
      await screen.findByText("飞书登录尚未启用，请联系管理员完成接入配置。"),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "使用飞书登录" })).toBeNull();
  });
  it("临时授权过期后移除下载 URL 并允许重新获取", async () => {
    downloadReads();
    vi.mocked(write).mockImplementation(
      async () =>
        ({
          download_url: "http://localhost/api/v1/downloads/expiring-grant",
          expires_at: new Date(Date.now() + 300).toISOString(),
          file_name: "demo.apk",
          size_bytes: 1024,
          sha256: "a".repeat(64),
        }) as never,
    );
    mount(<CatalogEntryPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "获取下载链接" }),
    );
    expect(
      await screen.findByRole("link", { name: "下载 1.0 KB" }),
    ).toBeTruthy();
    expect(
      await screen.findByRole("button", { name: "链接已过期，重新获取" }),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "下载 1.0 KB" })).toBeNull();
  });
  it("冷缓存202就绪后重新授权才给出普通下载链接", async () => {
    downloadReads();
    vi.mocked(write)
      .mockResolvedValueOnce({ ...prep, state: "queued" } as never)
      .mockResolvedValueOnce({
        download_url: "http://localhost/api/v1/downloads/test-grant",
        expires_at: new Date(Date.now() + 60_000).toISOString(),
        file_name: "demo.apk",
        size_bytes: 1024,
        sha256: "a".repeat(64),
      } as never);
    mount(<CatalogEntryPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "获取下载链接" }),
    );
    expect(
      await screen.findByText("文件已准备好，请再次获取临时下载链接。"),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: /下载 1.0 KB/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "获取临时下载链接" }));
    const link = await screen.findByRole("link", { name: "下载 1.0 KB" });
    expect(link.getAttribute("href")).toContain("/api/v1/downloads/test-grant");
    expect(link.getAttribute("download")).toBe("demo.apk");
    expect(vi.mocked(write).mock.calls[0]?.[3]?.key).not.toEqual(
      vi.mocked(write).mock.calls[1]?.[3]?.key,
    );
    expect(
      JSON.stringify(
        queryClient
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data),
      ),
    ).not.toContain("test-grant");
    expect(localStorage.length).toBe(0);
  });
  it("管理员会话不能以下载者身份打开包详情", async () => {
    vi.mocked(read).mockImplementation(async (path) =>
      path === "/api/v1/auth/bootstrap-status"
        ? ({ initialized: true, sso_enabled: true } as never)
        : ({
            ...session,
            user: { ...session.user, kind: "local", role: "admin" },
          } as never),
    );
    mount(<CatalogEntryPage />);
    expect(
      await screen.findByRole("link", { name: "使用飞书登录" }),
    ).toBeTruthy();
    expect(
      vi
        .mocked(read)
        .mock.calls.every(
          ([path]) =>
            path === "/api/v1/auth/browser-context" ||
            path === "/api/v1/auth/bootstrap-status",
        ),
    ).toBe(true);
  });
  it("未知投递结果必须勾选可能重复确认后才能重试", async () => {
    const delivery = {
      id: "delivery",
      event_id: null,
      app_id: null,
      chat_id: "chat",
      chat_name: "测试群",
      kind: "test",
      state: "unknown",
      attempts: 1,
      provider_message_id: null,
      error_code: "EXTERNAL_RESULT_UNKNOWN",
      error_message: "结果未知",
      created_at: "2026-10-01T00:00:00Z",
      updated_at: "2026-10-01T00:00:00Z",
      can_retry: true,
      card: {
        title: "测试卡片",
        summary: "通知摘要",
        app_name: null,
        mode: "debug",
        version_label: null,
        file_names: [],
        result: "test",
        occurred_at: "2026-10-01T00:00:00Z",
        page_url: null,
      },
    } satisfies DTO<"Delivery">;
    vi.mocked(read).mockResolvedValue(delivery as never);
    vi.mocked(write).mockResolvedValue({
      task_id: "task",
      status_url: "/api/v1/tasks/task",
    } as never);
    mount(
      <NotificationPage />,
      "/admin/notifications/delivery",
      "/admin/notifications/:id",
    );
    const button = await screen.findByRole("button", { name: "重试发送" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "我确认重试可能产生重复通知" }),
    );
    fireEvent.click(button);
    await waitFor(() =>
      expect(write).toHaveBeenCalledWith(
        "/api/v1/notifications/{id}/retry",
        "post",
        { acknowledge_possible_duplicate: true },
        expect.objectContaining({ id: "delivery", key: expect.any(String) }),
      ),
    );
  });
  it("登录保留密码空格并在成功后清理原身份的查询缓存", async () => {
    vi.mocked(read).mockResolvedValue({
      initialized: true,
      sso_enabled: false,
    } as never);
    vi.mocked(write).mockResolvedValue({
      user: {
        ...session.user,
        kind: "local",
        role: "admin",
        must_change_password: false,
      },
      csrf_token: "csrf",
      expires_at: "2026-10-02T00:00:00Z",
    } as never);
    mount(<LoginPage />, "/login", "/login");
    queryClient.setQueryData(["private-old-viewer"], { private: true });
    fireEvent.change(await screen.findByLabelText("密码 *"), {
      target: { value: "  password  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录后台" }));
    await screen.findByText("已进入后台");
    expect(write).toHaveBeenCalledWith("/api/v1/auth/login", "post", {
      username: "admin",
      password: "  password  ",
    });
    expect(queryClient.getQueryData(["private-old-viewer"])).toBeUndefined();
  });
  it("网络失败的手动重试复用意图键，成功后的新操作换键", async () => {
    const keys: string[] = [];
    let attempt = 0;
    function Harness() {
      const cmd = useCommand();
      return (
        <>
          {cmd.feedback}
          <button
            disabled={cmd.pending}
            onClick={() =>
              void cmd.run("intent", async (key) => {
                keys.push(key);
                if (attempt++ === 0) throw Error("网络中断");
              })
            }
          >
            执行
          </button>
        </>
      );
    }
    mount(<Harness />, "/test", "/test");
    fireEvent.click(screen.getByRole("button", { name: "执行" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "执行" }));
    await screen.findByText("请求已提交。");
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "执行" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "执行" }));
    await waitFor(() => expect(keys).toHaveLength(3));
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[1]);
  });
});
