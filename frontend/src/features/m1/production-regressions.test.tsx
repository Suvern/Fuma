// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { read, write } from "../../shared/api/http";
import { FeishuPage } from "./Feishu";
import { TasksPage } from "./Operations";
import { Component as AdminLayout } from "../../app/layouts/AdminLayout";
import Modal from "@douyinfe/semi-ui-19/lib/es/modal";

const realConfirm = Modal.confirm;

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
let client: QueryClient;
const task = {
  id: "task",
  kind: "cache_cleanup",
  state: "succeeded",
  phase: "done",
  progress: 100,
  created_at: "2026-10-04T08:00:00Z",
};
beforeEach(() => {
  vi.resetAllMocks();
  // jsdom does not run CSS animations; retain the real imperative render/adapter.
  vi.spyOn(Modal, "confirm").mockImplementation((props) =>
    realConfirm({ ...props, motion: false }),
  );
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  vi.mocked(read).mockImplementation(async (path) => {
    const data: Record<string, unknown> = {
      "/api/v1/settings/feishu": {
        revision: 1,
        app_id: "app",
        has_secret: true,
        verified: true,
        enabled: true,
        callback_url: "http://localhost/callback",
        checks: [],
      },
      "/api/v1/settings/feishu-bot": {
        revision: 1,
        bot_name: "Fuma",
        app_id: "app",
        verified: true,
        enabled: true,
        checks: [],
      },
      "/api/v1/settings/feishu-bot/chats": {
        items: [
          {
            chat_id: "test-chat",
            name: "test",
            membership: "joined",
            send_status: "unverified",
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
        sync_state: "ready",
      },
      "/api/v1/tasks/{id}": task,
      "/api/v1/tasks": { items: [], total: 0, page: 1, page_size: 20 },
      "/api/v1/apps/{id}": { id: "app", name: "Joice" },
      "/api/v1/auth/browser-context": {
        authenticated: true,
        viewer_key: "admin",
        user: { kind: "local", role: "admin", must_change_password: false },
      },
    };
    if (!(path in data)) throw new Error(`Unexpected read: ${path}`);
    return data[path] as never;
  });
});
afterEach(() => {
  cleanup();
  client.clear();
});
function mount(node: React.ReactNode, route = "/") {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

it("shows the real Semi confirmation, cancels without sending, and submits once after confirmation", async () => {
  vi.mocked(write).mockResolvedValue({
    task_id: "task",
    state: "queued",
  } as never);
  mount(<FeishuPage />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "test" }));
  const send = screen.getByRole("button", { name: "发送测试卡片到所选群" });
  fireEvent.click(send);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("向所选 1 个群发送测试卡片？")).toBeTruthy();
  expect(vi.mocked(write)).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(vi.mocked(write)).not.toHaveBeenCalled();
  fireEvent.click(send);
  fireEvent.click(send);
  const confirmed = await screen.findByRole("dialog");
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  fireEvent.click(within(confirmed).getByRole("button", { name: "确认继续" }));
  await waitFor(() => expect(write).toHaveBeenCalledTimes(1));
  expect(write).toHaveBeenCalledWith(
    "/api/v1/settings/feishu-bot/test-message",
    "post",
    { chat_ids: ["test-chat"] },
    { key: expect.any(String) },
  );
  expect(await screen.findByText("请求已提交。")).toBeTruthy();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("shows send errors next to the action and keeps the selected group for retry", async () => {
  vi.mocked(write).mockRejectedValue(new Error("测试投递失败，请重试"));
  mount(<FeishuPage />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "test" }));
  fireEvent.click(screen.getByRole("button", { name: "发送测试卡片到所选群" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: "确认继续",
    }),
  );
  expect(await screen.findByText("测试投递失败，请重试")).toBeTruthy();
  expect(
    (screen.getByRole("checkbox", { name: "test" }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "发送测试卡片到所选群",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("distinguishes no data from no matches and resets both the query and search field", async () => {
  mount(<TasksPage />);
  expect(await screen.findByText("暂无任务")).toBeTruthy();
  const search = screen.getByRole("searchbox", {
    name: "搜索任务类型或资源标识",
  });
  fireEvent.change(search, { target: { value: "缓存清理" } });
  fireEvent.click(screen.getByRole("button", { name: "搜索" }));
  expect(await screen.findByText("没有匹配的任务")).toBeTruthy();
  expect(read).toHaveBeenCalledWith("/api/v1/tasks", {
    query: { page: 1, q: "缓存清理" },
  });
  fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));
  expect(await screen.findByText("暂无任务")).toBeTruthy();
  expect((search as HTMLInputElement).value).toBe("");
});

it("retains the app breadcrumb on subpages and has only one main landmark", async () => {
  mount(
    <Routes>
      <Route path="/admin" element={<AdminLayout />}>
        <Route path="apps/:appId/debug" element={<h1>Debug 包管理</h1>} />
      </Route>
    </Routes>,
    "/admin/apps/app/debug",
  );
  const breadcrumb = await screen.findByRole("navigation", {
    name: "Breadcrumb",
  });
  expect(
    await within(breadcrumb).findByRole("link", { name: "Joice" }),
  ).toBeTruthy();
  expect(
    within(breadcrumb)
      .getByRole("link", { name: "应用管理" })
      .getAttribute("href"),
  ).toBe("/admin/apps");
  expect(within(breadcrumb).getByText("Debug 包")).toBeTruthy();
  expect(screen.getAllByRole("main")).toHaveLength(1);
});
