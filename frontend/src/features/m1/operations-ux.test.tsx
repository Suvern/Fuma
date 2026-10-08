// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { read } from "../../shared/api/http";
import { TasksPage, TaskPage, NotificationPage } from "./Operations";
import { TaskOverview } from "../system/components/TaskOverview";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
let queryClient: QueryClient;
const task = {
  id: "task",
  kind: "package_ingest",
  state: "succeeded",
  phase: "done",
  progress: 100,
  category: "business",
  app_id: "app",
  app_name: "SomeProject",
  resource_name: "release.ipa",
  resource_url: "/admin/apps/app/packages",
  result_summary: "安装包已解析并入库；发布仍需单独操作。",
  attempts: 1,
  created_at: "2026-10-04T00:00:00Z",
  updated_at: "2026-10-04T00:00:00Z",
  next_check_at: null,
  error_code: null,
  error_message: null,
  can_retry: false,
};
beforeEach(() => {
  vi.resetAllMocks();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/tasks/{id}") return task as never;
    return { items: [task], total: 1, page: 1, page_size: 20 } as never;
  });
});
afterEach(() => {
  cleanup();
  queryClient.clear();
});
function mount(children: React.ReactNode, path = "/admin/tasks") {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
    </QueryClientProvider>,
  );
}

it("defaults to business tasks and explicitly exposes system/all groups", async () => {
  mount(<TasksPage />);
  expect(await screen.findByText("SomeProject · release.ipa")).toBeTruthy();
  expect(read).toHaveBeenCalledWith("/api/v1/tasks", {
    query: { page: 1, q: "", category: "business" },
  });
  fireEvent.click(screen.getByRole("button", { name: "系统维护" }));
  await waitFor(() =>
    expect(read).toHaveBeenCalledWith("/api/v1/tasks", {
      query: { page: 1, q: "", category: "system" },
    }),
  );
  expect(
    screen
      .getByRole("button", { name: "系统维护" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "全部任务" }));
  await waitFor(() =>
    expect(read).toHaveBeenCalledWith("/api/v1/tasks", {
      query: { page: 1, q: "", category: "all" },
    }),
  );
});

it("shows a result and business links, then returns to the original filters", async () => {
  mount(
    <Routes>
      <Route path="/admin/tasks" element={<TasksPage />} />
      <Route path="/admin/tasks/:id" element={<TaskPage />} />
    </Routes>,
    "/admin/tasks?category=all&q=SomeProject&page=2",
  );
  fireEvent.click(await screen.findByRole("link", { name: "安装包解析入库" }));
  expect(await screen.findByRole("heading", { name: "处理结果" })).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "查看release.ipa" }).getAttribute("href"),
  ).toBe("/admin/apps/app/packages");
  expect(screen.getByText(task.result_summary)).toBeTruthy();
  expect(screen.getByText("技术信息").closest("details")?.open).toBe(false);
  const back = screen.getByRole("link", { name: "← 返回任务列表" });
  expect(back.getAttribute("href")).toBe(
    "/admin/tasks?category=all&q=SomeProject&page=2",
  );
  fireEvent.click(back);
  expect(await screen.findByDisplayValue("SomeProject")).toBeTruthy();
});

it("test notification preview omits empty app/version and Debug fields", async () => {
  vi.mocked(read).mockResolvedValue({
    id: "n",
    kind: "test",
    state: "succeeded",
    chat_name: "测试群",
    attempts: 1,
    card: {
      title: "连接检查",
      summary: "已完成测试",
      app_name: null,
      version_label: null,
      file_names: [],
      mode: "debug",
      result: "test",
      page_url: null,
    },
  } as never);
  mount(
    <Routes>
      <Route path="/admin/notifications/:id" element={<NotificationPage />} />
    </Routes>,
    "/admin/notifications/n",
  );
  expect(await screen.findByText("连接测试通知")).toBeTruthy();
  expect(screen.queryByText(/Debug/)).toBeNull();
  expect(screen.queryByText("·")).toBeNull();
});

it("homepage focuses business work while retaining failed maintenance and full history links", async () => {
  vi.mocked(read).mockImplementation(
    async (_path, options) =>
      ({
        items:
          options?.query?.state === "failed"
            ? [
                {
                  ...task,
                  id: "failed",
                  kind: "cache_cleanup",
                  state: "failed",
                  category: "system",
                  app_name: null,
                  resource_name: "本地文件缓存",
                  result_summary: null,
                },
              ]
            : [task],
        total: 1,
        page: 1,
        page_size: 4,
      }) as never,
  );
  mount(<TaskOverview />);
  expect(await screen.findByText("失败待排查")).toBeTruthy();
  expect(screen.getByText("SomeProject · release.ipa")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "查看全部任务" }).getAttribute("href"),
  ).toBe("/admin/tasks?category=all");
  expect(read).toHaveBeenCalledWith("/api/v1/tasks", {
    query: { category: "business", page: 1, page_size: 4 },
  });
});
