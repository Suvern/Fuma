// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { ApiError, read, write, type DTO } from "../../shared/api/http";
import { ConnectorsPage } from "./Connectors";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
const connector: DTO<"Connector"> = {
  id: "connector",
  name: "团队连接",
  enabled: true,
  has_token: true,
  github_login: "owner",
  revision: 1,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  last_tested_at: null,
  last_test_status: "untested",
  last_error_code: null,
};
const result: DTO<"ConnectionTestResult"> = {
  status: "failed",
  tested_at: "2026-10-03T00:00:00Z",
  checks: [
    { code: "identity", status: "pass", message: "账号身份已验证" },
    {
      code: "contents",
      status: "fail",
      message: "Release 列表读取被拒绝（403）",
      required_permission: "Contents · Read-only",
      remediation: "请检查目标仓库授权与 Contents 读取权限。",
      error_code: "GITHUB_FORBIDDEN",
      endpoint: "GET /repos/owner/repo/releases",
    },
  ],
};
let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {
      configurable: true,
      value: function (this: HTMLDialogElement) {
        this.open = true;
      },
    },
    close: {
      configurable: true,
      value: function (this: HTMLDialogElement) {
        this.open = false;
      },
    },
  });
  vi.mocked(read).mockResolvedValue({
    items: [connector],
    page: 1,
    page_size: 20,
    total: 1,
  });
});
afterEach(() => {
  cleanup();
  client.clear();
});
async function mount() {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ConnectorsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "团队连接" });
}
async function check() {
  fireEvent.change(screen.getByLabelText(/^目标仓库/), {
    target: { value: "owner/repo" },
  });
  fireEvent.click(screen.getByRole("button", { name: "检查连接" }));
  await screen.findByText("需要处理以下问题");
}
it("displays actionable failures without generic success or one-page pagination", async () => {
  vi.mocked(write).mockResolvedValue(result);
  await mount();
  await check();
  expect(screen.queryByText("请求已提交。")).toBeNull();
  expect(screen.getByText(result.checks[1]!.remediation!)).toBeTruthy();
  expect(screen.getByText("1 项未通过")).toBeTruthy();
  expect(screen.queryByRole("navigation", { name: "分页" })).toBeNull();
  expect(vi.mocked(write).mock.calls[0]?.[2]).toEqual({
    repository_full_name: "owner/repo",
    check_actions: true,
  });
});
it("disables duplicate checks in flight and announces loading", async () => {
  let resolve!: (value: DTO<"ConnectionTestResult">) => void;
  vi.mocked(write).mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "检查连接" }));
  const button = screen.getByRole("button", { name: "正在检查…" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(button);
  expect(write).toHaveBeenCalledTimes(1);
  expect(screen.getByText("正在连接 GitHub…")).toBeTruthy();
  await act(async () => resolve(result));
});
it("marks results stale when the target changes and retains the original scope", async () => {
  vi.mocked(write).mockResolvedValue(result);
  await mount();
  await check();
  fireEvent.change(screen.getByLabelText(/^目标仓库/), {
    target: { value: "owner/another" },
  });
  expect(screen.getByText("检查条件已更改")).toBeTruthy();
  expect(screen.getByText(/下方是 owner\/repo 的上次结果/)).toBeTruthy();
});
it("identity-only checks omit Actions and describe incomplete verification", async () => {
  vi.mocked(write).mockResolvedValue({
    ...result,
    status: "partial",
    checks: [
      { code: "identity", status: "pass", message: "账号身份已验证" },
      { code: "contents", status: "unknown", message: "填写仓库以继续检查" },
    ],
  });
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "检查连接" }));
  await screen.findByText("部分项目尚待验证");
  expect(vi.mocked(write).mock.calls[0]?.[2]).toEqual({ check_actions: false });
  expect(screen.queryByText("所选检查全部通过")).toBeNull();
});
it("saving an edit retains feedback and invalidates previous diagnostics", async () => {
  vi.mocked(write)
    .mockResolvedValueOnce(result)
    .mockResolvedValueOnce({ ...connector, revision: 2 });
  await mount();
  await check();
  fireEvent.click(screen.getByRole("button", { name: "编辑连接" }));
  expect((screen.getByLabelText(/^替换令牌/) as HTMLInputElement).value).toBe(
    "",
  );
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  await screen.findByText("连接已保存。请重新检查仓库权限。");
  expect(screen.queryByText(result.checks[1]!.message)).toBeNull();
  // Dialog stays mounted until the leave animation completes; jsdom has no CSS animation.
  await act(async () => {
    document.querySelectorAll(".semi-modal-mask-animate-hide").forEach((mask) => {
      fireEvent.animationEnd(mask);
      fireEvent(mask, new Event("webkitAnimationEnd", { bubbles: true }));
    });
  });
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("provider authorization errors do not suggest logging into Fuma again", async () => {
  vi.mocked(write).mockRejectedValue(
    new ApiError(403, {
      code: "GITHUB_BAD_CREDENTIAL",
      message: "GitHub 凭据已失效",
      retryable: false,
    }),
  );
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "编辑连接" }));
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  await screen.findByText("GitHub 凭据已失效");
  expect(screen.queryByText("重新登录")).toBeNull();
  expect(screen.getByRole("dialog")).toBeTruthy();
});
it("canceling deletion never sends a delete request", async () => {
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "编辑连接" }));
  fireEvent.click(screen.getByRole("button", { name: "删除连接…" }));
  expect(
    screen.getByRole("dialog", { name: "删除连接「团队连接」？" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(write).not.toHaveBeenCalled();
});
it("search sends connector name and can be cleared", async () => {
  await mount();
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "team" },
  });
  fireEvent.click(screen.getByRole("button", { name: "搜索" }));
  await waitFor(() =>
    expect(read).toHaveBeenLastCalledWith("/api/v1/connectors/github", {
      query: { page: 1, q: "team" },
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "清除" }));
  await waitFor(() =>
    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe(""),
  );
});

it("a failed retry clears previous diagnostics instead of showing stale success", async () => {
  vi.mocked(write)
    .mockResolvedValueOnce(result)
    .mockRejectedValueOnce(new Error("网络请求未完成"));
  await mount();
  await check();
  fireEvent.click(screen.getByRole("button", { name: "重新检查" }));
  await screen.findByText("网络请求未完成");
  expect(screen.queryByText(result.checks[1]!.message)).toBeNull();
});

it("prevents closing the save dialog while a request is pending", async () => {
  let resolve!: (value: DTO<"Connector">) => void;
  vi.mocked(write).mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "编辑连接" }));
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  const dialog = screen.getByRole("dialog");
  expect(screen.queryByRole("button", { name: "close" })).toBeNull();
  fireEvent.keyDown(document, { key: "Escape", code: "Escape", keyCode: 27 });
  expect(screen.getByRole("dialog")).toBe(dialog);
  expect(
    (screen.getByRole("button", { name: "取消" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  await act(async () => resolve({ ...connector, revision: 2 }));
});
