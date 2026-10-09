// @vitest-environment jsdom
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { read } from "../../shared/api/http";
import { FeishuAutoLogin } from "./FeishuAutoLogin";
import { isFeishuBrowser, suppressAutomaticFeishuLogin } from "./feishu-auto-login";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
}));

let client: QueryClient;
const navigate = vi.fn();
function mount(path = "/", ready = true, authenticated = false) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <FeishuAutoLogin sessionReady={ready} authenticated={authenticated} navigate={navigate} />
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 Mobile Safari/537.36 Lark/7.54.0 LarkLocale/zh_CN ChannelName/Feishu");
  vi.mocked(read).mockResolvedValue({ initialized: true, sso_enabled: true } as never);
});
afterEach(() => {
  cleanup();
  client?.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe("飞书内自动登录", () => {
  it.each([
    ["/", "/"],
    ["/debug/package?platform=android#download", "/debug/package?platform=android#download"],
    ["/apps/one", "/apps/one"],
    ["/releases/one", "/releases/one"],
    ["/login?return_to=%2Fadmin%2Fapps", "/admin/apps"],
    ["/login?return_to=https%3A%2F%2Fevil.example", "/"],
  ])("未登录时从 %s 自动登录并返回 %s", async (path, target) => {
    mount(path);
    await waitFor(() => expect(navigate).toHaveBeenCalledExactlyOnceWith(
      `/api/v1/auth/feishu/start?return_to=${encodeURIComponent(target)}`,
    ));
  });

  it("StrictMode、重新挂载和刷新缓存不会重复发起登录", async () => {
    const first = mount();
    await waitFor(() => expect(navigate).toHaveBeenCalledOnce());
    await act(async () => { await client.invalidateQueries({ queryKey: ["bootstrap"] }); });
    first.unmount();
    client.clear();
    mount("/debug/another");
    await waitFor(() => expect(client.getQueryState(["bootstrap"])?.status).toBe("success"));
    expect(navigate).toHaveBeenCalledOnce();
  });

  it.each(["/login?error=OAUTH_CANCELLED", "/auth/error"])("授权失败页 %s 不自动登录，返回首页也不重试", async (path) => {
    const errorPage = mount(path);
    await waitFor(() => expect(client.getQueryState(["bootstrap"])?.status).toBe("success"));
    errorPage.unmount();
    client.clear();
    mount();
    await waitFor(() => expect(client.getQueryState(["bootstrap"])?.status).toBe("success"));
    expect(navigate).not.toHaveBeenCalled();
  });

  it.each([[false, false], [true, true]])("会话未确定或已经登录时不跳转（ready=%s, authenticated=%s）", async (ready, authenticated) => {
    mount("/", ready, authenticated);
    expect(read).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it.each([
    { initialized: true, sso_enabled: false },
    { initialized: false, sso_enabled: true },
  ])("SSO 不可用时保持当前页面：%o", async (status) => {
    vi.mocked(read).mockResolvedValue(status as never);
    mount();
    await waitFor(() => expect(client.getQueryState(["bootstrap"])?.status).toBe("success"));
    expect(navigate).not.toHaveBeenCalled();
  });

  it("接口失败不猜测登录状态或自动跳转", async () => {
    vi.mocked(read).mockRejectedValue(new Error("offline"));
    mount();
    await waitFor(() => expect(client.getQueryState(["bootstrap"])?.status).toBe("error"));
    expect(navigate).not.toHaveBeenCalled();
  });

  it("普通浏览器不触发自动登录", () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 Chrome/130.0.0.0 Safari/537.36");
    mount();
    expect(read).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("无法持久记录尝试时保留手动登录以避免循环", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    mount();
    await waitFor(() => expect(client.getQueryState(["bootstrap"])?.status).toBe("success"));
    expect(navigate).not.toHaveBeenCalled();
  });

  it("主动退出登录后不立即自动登录", async () => {
    suppressAutomaticFeishuLogin();
    mount();
    await waitFor(() => expect(client.getQueryState(["bootstrap"])?.status).toBe("success"));
    expect(navigate).not.toHaveBeenCalled();
  });

  it("识别飞书客户端标记，普通网页标题或相似标记不算", () => {
    expect(isFeishuBrowser("Mozilla/5.0 (iPhone) Feishu/7.54.0")).toBe(true);
    expect(isFeishuBrowser("Mozilla/5.0 Lark/7.54.0")).toBe(true);
    expect(isFeishuBrowser("Mozilla/5.0 LarkLocale/zh_CN")).toBe(false);
    expect(isFeishuBrowser("Mozilla/5.0 NotLark/7.54.0")).toBe(false);
  });
});
