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
import { MemoryRouter, Outlet, Route, Routes, useLocation } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { AdminGuard, LoginPage, PasswordPage } from "./Auth";
vi.mock("../../shared/api/http", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
const user: DTO<"SessionUser"> = {
  id: "admin-user",
  kind: "local",
  role: "admin",
  managed_app_ids: [],
  active: true,
  permission_revision: 1,
  display_name: "admin",
  tenant_key: null,
  must_change_password: true,
};
const context = (mustChange = true): DTO<"BrowserContext"> => ({
  authenticated: true,
  viewer_key: mustChange ? "initial-admin" : "changed-admin",
  csrf_token: "test-csrf",
  user: { ...user, must_change_password: mustChange },
});
let currentContext: DTO<"BrowserContext">;
let queryClient: QueryClient;
let initialized: boolean;
let signedIn: boolean;
function ProtectedContent() {
  useQuery({
    queryKey: ["protected-apps"],
    queryFn: () => read("/api/v1/apps"),
  });
  return <h1>后台应用页面</h1>;
}
function Location() {
  const location = useLocation();
  return (
    <output aria-label="当前路由">{location.pathname + location.search}</output>
  );
}
function mount(path: string) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Location />
        <Routes>
          <Route path="/" element={<h1>下载首页</h1>} />
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/admin"
            element={
              <AdminGuard>
                <Outlet />
              </AdminGuard>
            }
          >
            <Route index element={<ProtectedContent />} />
            <Route path="apps" element={<ProtectedContent />} />
            <Route path="settings/account" element={<PasswordPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  initialized = true;
  signedIn = true;
  currentContext = context();
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/auth/browser-context") return (signedIn
      ? currentContext
      : { authenticated: false, viewer_key: "anonymous", user: null }) as never;
    if (path === "/api/v1/auth/bootstrap-status")
      return { initialized, sso_enabled: false } as never;
    if (path === "/api/v1/apps")
      return { items: [], page: 1, page_size: 20, total: 0 } as never;
    throw Error("unexpected request");
  });
  vi.mocked(write).mockImplementation(async (path) => {
    if (path === "/api/v1/auth/login") signedIn = true;
    if (path === "/api/v1/auth/password") currentContext = context(false);
    return {
      user: currentContext.user,
      csrf_token: "new-csrf",
      expires_at: "2026-10-02T00:00:00Z",
    } as never;
  });
});
afterEach(() => {
  cleanup();
  queryClient?.clear();
});

describe("自动管理员初始化与强制改密", () => {
  it("登录页仅提示日志中的初始密码，服务未就绪时不开放登录或手工初始化", async () => {
    initialized = false;
    signedIn = false;
    mount("/login");
    expect(await screen.findByText(/docker compose .*logs api/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "登录后台" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.queryByLabelText(/初始化令牌/)).toBeNull();
    expect(screen.queryByRole("button", { name: "初始化并登录" })).toBeNull();
    expect(screen.getByLabelText("密码 *").getAttribute("autocomplete")).toBe(
      "current-password",
    );
    expect(write).not.toHaveBeenCalled();
  });
  it("首次登录进入强制改密页，保留后台目标且不提前调用业务接口", async () => {
    signedIn = false;
    mount("/login?return_to=%2Fadmin%2Fapps");
    fireEvent.change(await screen.findByLabelText("密码 *"), {
      target: { value: "temporary-admin-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录后台" }));
    expect(
      await screen.findByRole("heading", { name: "首次登录：修改密码" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("当前路由").textContent).toBe(
      "/admin/settings/account?return_to=%2Fadmin%2Fapps",
    );
    expect(
      vi.mocked(read).mock.calls.some(([path]) => path === "/api/v1/apps"),
    ).toBe(false);
    expect(localStorage.length).toBe(0);
  });
  it("直接输入后台地址无法绕过改密，改密页本身不会循环重定向", async () => {
    mount("/admin/apps");
    expect(
      await screen.findByRole("heading", { name: "首次登录：修改密码" }),
    ).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "后台应用页面" })).toBeNull();
    expect(screen.getByLabelText("当前路由").textContent).toBe(
      "/admin/settings/account?return_to=%2Fadmin%2Fapps",
    );
    expect(
      vi.mocked(read).mock.calls.some(([path]) => path === "/api/v1/apps"),
    ).toBe(false);
    expect(screen.getByRole("button", { name: "修改密码" })).toBeTruthy();
  });
  it("拒绝与当前密码相同的新密码，且不向服务器发送改密请求", async () => {
    mount("/admin/settings/account");
    await screen.findByRole("heading", { name: "首次登录：修改密码" });
    fireEvent.change(screen.getByLabelText(/^当前密码/), {
      target: { value: "temporary-admin-password" },
    });
    fireEvent.change(screen.getByLabelText(/^新密码/), {
      target: { value: "temporary-admin-password" },
    });
    fireEvent.change(screen.getByLabelText(/^确认新密码/), {
      target: { value: "temporary-admin-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "修改密码" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "新密码不能与当前密码相同。",
    );
    expect(write).not.toHaveBeenCalled();
  });
  it("改密成功刷新会话、清除旧缓存并回到原后台页面", async () => {
    mount("/admin/settings/account?return_to=%2Fadmin%2Fapps");
    await screen.findByRole("heading", { name: "首次登录：修改密码" });
    queryClient.setQueryData(["old-private-data"], { private: true });
    fireEvent.change(screen.getByLabelText(/^当前密码/), {
      target: { value: "temporary-admin-password" },
    });
    fireEvent.change(screen.getByLabelText(/^新密码/), {
      target: { value: "  a-new-admin-password  " },
    });
    fireEvent.change(screen.getByLabelText(/^确认新密码/), {
      target: { value: "  a-new-admin-password  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "修改密码" }));
    expect(
      await screen.findByRole("heading", { name: "后台应用页面" }),
    ).toBeTruthy();
    expect(write).toHaveBeenCalledWith("/api/v1/auth/password", "post", {
      old_password: "temporary-admin-password",
      new_password: "  a-new-admin-password  ",
    });
    expect(screen.getByLabelText("当前路由").textContent).toBe("/admin/apps");
    expect(queryClient.getQueryData(["old-private-data"])).toBeUndefined();
    expect(
      queryClient.getQueryData<DTO<"BrowserContext">>(["session"])?.user
        ?.must_change_password,
    ).toBe(false);
    const browserReads = vi
      .mocked(read)
      .mock.calls.map(([path], index) =>
        path === "/api/v1/auth/browser-context"
          ? vi.mocked(read).mock.invocationCallOrder[index]
          : 0,
      );
    expect(Math.max(...browserReads.map((x) => x ?? 0))).toBeGreaterThan(
      vi.mocked(write).mock.invocationCallOrder[0]!,
    );
  });
  it("已完成改密的管理员正常登录直达目标页面", async () => {
    signedIn = false;
    currentContext = context(false);
    mount("/login?return_to=%2Fadmin%2Fapps");
    fireEvent.change(await screen.findByLabelText("密码 *"), {
      target: { value: "personal-admin-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录后台" }));
    await screen.findByRole("heading", { name: "后台应用页面" });
    expect(
      screen.queryByRole("heading", { name: "首次登录：修改密码" }),
    ).toBeNull();
    await waitFor(() =>
      expect(
        vi.mocked(read).mock.calls.some(([path]) => path === "/api/v1/apps"),
      ).toBe(true),
    );
  });
  it.each([
    ["/login", "/admin"],
    ["/login?return_to=%2Fadmin%2Fapps", "/admin/apps"],
    ["/login?return_to=%2Flogin%2F%3Freturn_to%3D%252Fadmin", "/admin"],
    ["/login?return_to=https%3A%2F%2Fexample.com", "/admin"],
  ])("已有管理员会话访问 %s 直接进入 %s", async (path, expected) => {
    currentContext = context(false);
    mount(path);
    expect(screen.queryByLabelText("密码 *")).toBeNull();
    await screen.findByRole("heading", { name: "后台应用页面" });
    expect(screen.getByLabelText("当前路由").textContent).toBe(expected);
    expect(screen.queryByLabelText("密码 *")).toBeNull();
    expect(write).not.toHaveBeenCalled();
  });
  it("已有会话但尚未改密时直接进入改密页", async () => {
    mount("/login?return_to=%2Fadmin%2Fapps");
    await screen.findByRole("heading", { name: "首次登录：修改密码" });
    expect(screen.getByLabelText("当前路由").textContent).toBe("/admin/settings/account?return_to=%2Fadmin%2Fapps");
    expect(screen.queryByRole("button", { name: "登录后台" })).toBeNull();
    expect(write).not.toHaveBeenCalled();
  });
  it("已登录的下载用户返回下载首页，不展示管理员登录表单", async () => {
    currentContext = { ...context(false), user: { ...user, kind: "feishu", role: "downloader", must_change_password: false } };
    mount("/login?return_to=%2Fadmin");
    await screen.findByRole("heading", { name: "下载首页" });
    expect(screen.queryByLabelText("密码 *")).toBeNull();
    expect(write).not.toHaveBeenCalled();
  });
  it("已有会话的飞书绑定失败保留错误与返回入口，不要求重复登录", async () => {
    currentContext = context(false);
    mount("/login?error=AUTH_FAILED&return_to=%2Fadmin%2Fsettings%2Ffeishu");
    await screen.findByRole("link", { name: "返回接入设置" });
    expect(screen.getByRole("alert").textContent).toContain("飞书验证未完成");
    expect(screen.queryByLabelText("密码 *")).toBeNull();
  });
});
