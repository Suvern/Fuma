// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import Modal from "@douyinfe/semi-ui-19/lib/es/modal";
import { Component as AdminLayout } from "../../app/layouts/AdminLayout";
import { Component as Home } from "../system/pages/AdminHomePage";
import { ApiError, read, write, type DTO } from "../../shared/api/http";
import { AppsPage } from "./Apps";
import { AccountPage } from "./Account";
import { MembersPage } from "./Members";
import { StorageChoice } from "../library/Storage";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
const appId = "11111111-1111-4111-8111-111111111111";
const memberId = "22222222-2222-4222-8222-222222222222";
let context: DTO<"BrowserContext">;
let client: QueryClient;
let otherRevoked: boolean;
const member: DTO<"MemberInfo"> = {
  id: memberId,
  kind: "feishu",
  display_name: "测试维护者",
  tenant_key: "tenant",
  provider_app_id: "provider",
  open_id: "ou_test",
  role: "maintainer",
  managed_app_ids: [appId],
  active: true,
  permission_revision: 4,
  identity_verified: true,
  permission_changed_at: null,
};
const apps = {
  items: [
    {
      id: appId,
      name: "已授权应用",
      public_slug: "managed",
      description: "",
      platforms: ["android"],
      enabled: true,
      revision: 1,
      debug_entry_count: 0,
      allowed_package_ids: [],
      created_at: "2026-10-04T00:00:00Z",
      updated_at: "2026-10-04T00:00:00Z",
      repository: null,
    },
  ],
  page: 1,
  page_size: 20,
  total: 1,
};
function ForbiddenResource() {
  useQuery({
    queryKey: ["forbidden"],
    queryFn: () => read("/api/v1/settings/storage-locations"),
  });
  return <h1>全局设置内容</h1>;
}
function mount(path: string, role: DTO<"SessionUser">["role"] = "maintainer") {
  context.user!.role = role;
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Home />} />
            <Route path="apps" element={<AppsPage />} />
            <Route path="settings/storage" element={<ForbiddenResource />} />
            <Route path="settings/account" element={<AccountPage />} />
            <Route path="settings/members" element={<MembersPage />} />
            <Route
              path="storage-choice"
              element={
                <StorageChoice
                  appId={appId}
                  mode="private"
                  value="default"
                  onChange={() => {}}
                />
              }
            />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  otherRevoked = false;
  context = {
    authenticated: true,
    viewer_key: "feishu-user",
    csrf_token: "test",
    user: {
      id: memberId,
      kind: "feishu",
      display_name: "测试维护者",
      tenant_key: "tenant",
      role: "maintainer",
      active: true,
      permission_revision: 4,
      managed_app_ids: [appId],
      must_change_password: false,
    },
  };
  const confirm = Modal.confirm;
  vi.spyOn(Modal, "confirm").mockImplementation((options) =>
    confirm({ ...options, motion: false }),
  );
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {
      configurable: true,
      value() {
        this.open = true;
      },
    },
    close: {
      configurable: true,
      value() {
        this.open = false;
      },
    },
  });
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/auth/browser-context") return context as never;
    if (path === "/api/v1/apps") return apps as never;
    if (path === "/api/v1/apps/{id}") return apps.items[0] as never;
    if (path === "/api/v1/settings/members")
      return { items: [member], total: 1, page: 1, page_size: 20 } as never;
    if (path === "/api/v1/auth/sessions")
      return {
        items: [
          {
            id: "current",
            kind: "feishu",
            current: true,
            created_at: "2026-10-04T00:00:00Z",
            authenticated_at: "2026-10-04T00:00:00Z",
            expires_at: "2026-10-05T00:00:00Z",
            revoked_at: null,
            state: "active",
          },
          {
            id: "other",
            kind: "feishu",
            current: false,
            created_at: "2026-10-03T00:00:00Z",
            authenticated_at: "2026-10-03T00:00:00Z",
            expires_at: "2026-10-05T00:00:00Z",
            revoked_at: otherRevoked ? "2026-10-04T01:00:00Z" : null,
            state: otherRevoked ? "revoked" : "active",
          },
        ],
        total: 2,
        page: 1,
        page_size: 20,
      } as never;
    if (path === "/api/v1/apps/{id}/available-storage")
      return {
        items: [
          {
            id: "private-store",
            name: "可用私有存储",
            provider: "cos",
            read_mode: "private",
            is_default: true,
          },
        ],
      } as never;
    if (path === "/api/v1/tasks")
      return { items: [], total: 0, page: 1, page_size: 20 } as never;
    throw new Error(`Unexpected endpoint: ${path}`);
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
});

describe("后台角色与自身会话", () => {
  it("维护者首页仅请求应用和任务，导航隐藏全部全局设置", async () => {
    mount("/admin");
    await screen.findByRole("heading", { name: "我的工作台" });
    await screen.findByText("已授权应用");
    for (const name of [
      "GitHub 连接",
      "对象存储",
      "飞书与机器人",
      "成员与角色",
      "本地缓存",
    ])
      expect(screen.queryByRole("link", { name })).toBeNull();
    expect(
      vi
        .mocked(read)
        .mock.calls.some(
          ([path]) =>
            path.startsWith("/api/v1/settings/") ||
            path.startsWith("/api/v1/connectors/") ||
            path === "/api/v1/system/health",
        ),
    ).toBe(false);
    expect(
      screen.getByRole("link", { name: "测试维护者 账号与会话" }),
    ).toBeTruthy();
  });
  it("维护者直接访问全局路由不会挂载页面或调用设置接口", async () => {
    mount("/admin/settings/storage");
    await screen.findByRole("heading", { name: "此页面需要管理员权限" });
    expect(screen.queryByText("全局设置内容")).toBeNull();
    expect(
      vi
        .mocked(read)
        .mock.calls.some(
          ([path]) => path === "/api/v1/settings/storage-locations",
        ),
    ).toBe(false);
  });
  it("无角色飞书用户明确提示后台无权，不触发业务查询", async () => {
    mount("/admin", "downloader");
    await screen.findByRole("heading", { name: "暂无后台权限" });
    expect(screen.getByRole("link", { name: "前往下载门户" })).toBeTruthy();
    expect(
      vi
        .mocked(read)
        .mock.calls.every(([path]) => path === "/api/v1/auth/browser-context"),
    ).toBe(true);
  });
  it("维护者无法通过new参数打开创建应用表单", async () => {
    mount("/admin/apps?new=1");
    await screen.findByText("已授权应用");
    expect(screen.queryByRole("button", { name: "新建应用" })).toBeNull();
    expect(screen.queryByLabelText(/应用名称/)).toBeNull();
  });
  it("存储选择器只读当前应用可用摘要", async () => {
    mount("/admin/storage-choice");
    await screen.findByRole("option", { name: /可用私有存储/ });
    expect(read).toHaveBeenCalledWith("/api/v1/apps/{id}/available-storage", {
      id: appId,
    });
    expect(
      vi
        .mocked(read)
        .mock.calls.some(
          ([path]) => path === "/api/v1/settings/storage-locations",
        ),
    ).toBe(false);
    expect(screen.queryByRole("link", { name: "配置或测试云存储" })).toBeNull();
  });
  it("飞书账号显示自己的会话但不出现本地密码，注销失败保留状态", async () => {
    vi.mocked(write).mockRejectedValueOnce(new Error("注销未完成"));
    mount("/admin/settings/account");
    await screen.findByText("当前会话");
    expect(screen.queryByLabelText(/^当前密码/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "注销其他会话" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认继续" }));
    await screen.findByText("注销未完成");
    expect(screen.queryByText("已注销")).toBeNull();
    vi.mocked(write).mockImplementation(async () => {
      otherRevoked = true;
      return { revoked_count: 1 } as never;
    });
    fireEvent.click(screen.getByRole("button", { name: "注销其他会话" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认继续" }));
    await screen.findByText("其他活动会话已注销，当前登录保留。");
    await waitFor(() =>
      expect(screen.getAllByText(/已注销/).length).toBeGreaterThan(1),
    );
  });
  it("成员编辑确认授权范围，冲突时保留草稿和旧修订", async () => {
    vi.mocked(write).mockRejectedValue(
      new ApiError(412, {
        code: "REVISION_CONFLICT",
        message: "权限已被其他管理员修改，请刷新",
        retryable: false,
      }),
    );
    mount("/admin/settings/members", "admin");
    fireEvent.click(await screen.findByRole("button", { name: "编辑授权" }));
    fireEvent.change(screen.getByLabelText("授予角色"), {
      target: { value: "admin" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认授权" }));
    await screen.findByRole("button", { name: "确认继续" });
    expect(
      screen.getAllByText(/可管理全部应用、成员和全局凭据/).length,
    ).toBeGreaterThan(0);
    expect(write).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认继续" }));
    await screen.findByText("权限已被其他管理员修改，请刷新");
    expect(write).toHaveBeenCalledWith(
      "/api/v1/settings/members/{id}/roles",
      "put",
      { role: "admin", managed_app_ids: [], active: true },
      { id: memberId, revision: 4 },
    );
    expect((screen.getByLabelText("授予角色") as HTMLSelectElement).value).toBe(
      "admin",
    );
    await waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: "放弃草稿并刷新权限",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false),
    );
  });
  it("成员按应用名称筛选，授权范围显示名称", async () => {
    mount("/admin/settings/members", "admin");
    await screen.findByRole("option", { name: "已授权应用" });
    expect(
      await screen.findByRole("link", { name: "已授权应用" }),
    ).toBeTruthy();
    expect(screen.queryByLabelText("授权 App ID（选填）")).toBeNull();
    fireEvent.change(screen.getByLabelText("授权应用"), {
      target: { value: appId },
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));
    await waitFor(() =>
      expect(read).toHaveBeenCalledWith(
        "/api/v1/settings/members",
        expect.objectContaining({
          query: expect.objectContaining({ app_id: appId }),
        }),
      ),
    );
  });
});
