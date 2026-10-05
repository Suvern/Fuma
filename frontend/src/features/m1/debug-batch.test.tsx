// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { DebugListPage } from "./Debug";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
let client: QueryClient;
let entries: DTO<"DebugEntry">[];
function entry(
  id: string,
  state: DTO<"CacheStatus">["state"] = "missing",
  enabled = true,
) {
  return {
    id,
    file_name: `${id}.apk`,
    app_id: "app",
    source_tag: "v1",
    revision: 7,
    enabled,
    platform: "android",
    size_bytes: 1024,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    build_number: null,
    version_name: null,
    version_label_source: "tag",
    mode: "debug",
    page_url: `/debug/${id}`,
    source: {
      asset_id: id,
      asset_updated_at: "2026-10-01T00:00:00Z",
      digest: null,
      release_id: "release",
      repository_id: "repo",
      repository_full_name: "owner/repo",
      size_bytes: 1024,
    },
    cache: {
      state,
      downloaded_bytes: 0,
      total_bytes: null,
      error_code: null,
      error_message: null,
      sha256: null,
      updated_at: null,
    },
  } satisfies DTO<"DebugEntry">;
}
beforeEach(() => {
  vi.resetAllMocks();
  entries = [entry("a"), entry("b")];
  vi.mocked(read).mockImplementation(async (path, options) => {
    if (path === "/api/v1/apps/{id}/debug-entries")
      return {
        items: options?.query?.page === 2 ? [entry("c")] : entries,
        page: options?.query?.page ?? 1,
        page_size: 2,
        total: 3,
      } as never;
    return {} as never;
  });
  vi.mocked(write).mockImplementation(async (path, _method, body, options) => {
    if (path === "/api/v1/debug-entries/{id}/precache")
      return { task_id: `task-${options?.id}`, status_url: "" } as never;
    entries = entries.map((item) =>
      item.id === options?.id
        ? {
            ...item,
            enabled: (body as DTO<"DebugEntryUpdate">).enabled,
            revision: item.revision + 1,
          }
        : item,
    );
    return entries.find((item) => item.id === options?.id) as never;
  });
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
});
async function mount() {
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/admin/apps/app/debug"]}>
        <Routes>
          <Route path="/admin/apps/:id/debug" element={<DebugListPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("checkbox", { name: "选择 a.apk" });
}
const checkbox = (name: string) =>
  screen.getByRole<HTMLInputElement>("checkbox", { name });
const button = (name: string) =>
  screen.getByRole<HTMLButtonElement>("button", { name });

it("逐项与当前页全选互相同步，翻页再返回不会恢复旧选择", async () => {
  await mount();
  expect(button("批量缓存 / 重试").disabled).toBe(true);
  fireEvent.click(checkbox("选择 a.apk"));
  expect(checkbox("全选当前页").indeterminate).toBe(true);
  fireEvent.click(checkbox("全选当前页"));
  expect(checkbox("选择 b.apk").checked).toBe(true);
  fireEvent.click(button("Next"));
  await screen.findByRole("checkbox", { name: "选择 c.apk" });
  expect(button("批量缓存 / 重试").disabled).toBe(true);
  fireEvent.click(button("Previous"));
  await screen.findByRole("checkbox", { name: "选择 a.apk" });
  expect(checkbox("选择 a.apk").checked).toBe(false);
  fireEvent.click(checkbox("全选当前页"));
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "query" },
  });
  fireEvent.click(button("搜索"));
  await waitFor(() => expect(button("批量缓存 / 重试").disabled).toBe(true));
  expect(write).not.toHaveBeenCalled();
});

it("批量缓存跳过就绪和处理中条目，部分失败保留勾选且重试复用幂等键", async () => {
  entries = [
    entry("a"),
    entry("b", "failed"),
    entry("ready", "ready"),
    entry("queued", "queued"),
  ];
  const pending: Array<{
    resolve: (value: never) => void;
    reject: (error: Error) => void;
  }> = [];
  vi.mocked(write).mockImplementation(
    () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
  );
  await mount();
  fireEvent.click(checkbox("全选当前页"));
  fireEvent.click(button("批量缓存 / 重试"));
  expect(write).toHaveBeenCalledTimes(2);
  expect(button("批量启用").disabled).toBe(true);
  expect(button("Next").getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(button("批量缓存 / 重试"));
  expect(write).toHaveBeenCalledTimes(2);
  const retryKey = vi.mocked(write).mock.calls[1]?.[3]?.key;
  await act(async () => {
    pending[0]!.resolve({ task_id: "task-a" } as never);
    pending[1]!.reject(new Error("缓存请求失败"));
  });
  await screen.findByText(/批量缓存：已提交 1 个，跳过 2 个，失败 1 个/);
  expect(checkbox("选择 b.apk").checked).toBe(true);
  expect(checkbox("选择 a.apk").checked).toBe(false);
  fireEvent.click(button("查看逐项结果"));
  expect(
    screen.getByRole("link", { name: "查看缓存任务" }).getAttribute("href"),
  ).toBe("/admin/tasks/task-a");
  expect(screen.getByText("缓存已就绪")).toBeTruthy();
  await waitFor(() => expect(button("批量缓存 / 重试").disabled).toBe(false));
  vi.mocked(write).mockResolvedValue({ task_id: "task-b" } as never);
  fireEvent.click(button("批量缓存 / 重试"));
  await screen.findByText(/批量缓存：已提交 1 个，跳过 0 个，失败 0 个/);
  expect(vi.mocked(write).mock.calls[2]?.[3]).toMatchObject({
    id: "b",
    key: retryKey,
  });
});

it("缓存批量请求最多同时发送三个", async () => {
  entries = [entry("a"), entry("b"), entry("c"), entry("d"), entry("e")];
  const pending: Array<() => void> = [];
  let active = 0;
  let peak = 0;
  vi.mocked(write).mockImplementation(
    () =>
      new Promise((resolve) => {
        active++;
        peak = Math.max(active, peak);
        pending.push(() => {
          active--;
          resolve({ task_id: "task" } as never);
        });
      }),
  );
  await mount();
  fireEvent.click(checkbox("全选当前页"));
  fireEvent.click(button("批量缓存 / 重试"));
  expect(write).toHaveBeenCalledTimes(3);
  await act(async () => pending.shift()!());
  expect(write).toHaveBeenCalledTimes(4);
  await act(async () => pending.shift()!());
  expect(write).toHaveBeenCalledTimes(5);
  await act(async () => {
    pending.forEach((resolve) => resolve());
  });
  await screen.findByText(/批量缓存：已提交 5 个/);
  expect(peak).toBe(3);
});

it("批量停用先确认，取消不写入，确认只更新需变更项并携带 revision", async () => {
  entries = [entry("a"), entry("b", "missing", false)];
  await mount();
  fireEvent.click(checkbox("全选当前页"));
  fireEvent.click(button("批量停用"));
  const dialog = await screen.findByRole("dialog", { name: "确认操作" });
  fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
  expect(write).not.toHaveBeenCalled();
  await waitFor(() => expect(button("批量停用").disabled).toBe(false));
  fireEvent.click(button("批量停用"));
  fireEvent.click(
    within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
      "button",
      { name: "确认继续" },
    ),
  );
  await screen.findByText(/批量停用：成功 1 个，跳过 1 个，失败 0 个/);
  expect(write).toHaveBeenCalledTimes(1);
  expect(write).toHaveBeenCalledWith(
    "/api/v1/debug-entries/{id}",
    "patch",
    { enabled: false },
    { id: "a", revision: 7 },
  );
  await waitFor(() => expect(checkbox("全选当前页").disabled).toBe(false));
  fireEvent.click(checkbox("选择 a.apk"));
  fireEvent.click(button("批量启用"));
  await screen.findByText(/批量启用：成功 1 个/);
  expect(write).toHaveBeenLastCalledWith(
    "/api/v1/debug-entries/{id}",
    "patch",
    { enabled: true },
    { id: "a", revision: 8 },
  );
});
