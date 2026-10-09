// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import type { DTO } from "./http";
import { renewFeishuSession } from "./session-renewal";

const context = {
  authenticated: true,
  viewer_key: "session-one",
  csrf_token: "csrf",
  eligibility_expires_at: "2026-10-09T04:00:00Z",
  user: {
    id: "user",
    kind: "feishu",
    display_name: "用户",
    role: "downloader",
    active: true,
    must_change_password: false,
  },
} as DTO<"BrowserContext">;
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-09T04:01:00Z"));
  sessionStorage.clear();
  window.history.replaceState({}, "", "/apps/demo?q=test#packages");
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("过期后重新验证并保留原页面，同一会话只尝试一次", async () => {
  const navigate = vi.fn();
  const load = vi.fn().mockResolvedValue(context);
  expect(await renewFeishuSession(load, { navigate })).toBe(true);
  expect(navigate).toHaveBeenCalledWith(
    "/api/v1/auth/feishu/start?return_to=%2Fapps%2Fdemo%3Fq%3Dtest%23packages",
  );
  expect(await renewFeishuSession(load, { navigate })).toBe(false);
  expect(navigate).toHaveBeenCalledTimes(1);
  vi.advanceTimersByTime(300_000);
  expect(
    await renewFeishuSession(
      async () => ({ ...context, viewer_key: "session-two" }),
      { navigate },
    ),
  ).toBe(true);
});
it("并发资格失败只触发一次跳转", async () => {
  const navigate = vi.fn();
  const load = vi.fn().mockResolvedValue(context);
  await Promise.all([
    renewFeishuSession(load, { navigate, force: true }),
    renewFeishuSession(load, { navigate, force: true }),
  ]);
  expect(load).toHaveBeenCalledTimes(1);
  expect(navigate).toHaveBeenCalledTimes(1);
});
it.each([
  { ...context, authenticated: false },
  { ...context, user: { ...context.user!, kind: "local" } },
  { ...context, user: { ...context.user!, active: false } },
  { ...context, eligibility_expires_at: "2026-10-09T05:00:00Z" },
  { ...context, eligibility_expires_at: null },
])("未登录、管理员、停用或未到期时不跳转", async (value) => {
  const navigate = vi.fn();
  expect(
    await renewFeishuSession(async () => value as DTO<"BrowserContext">, {
      navigate,
    }),
  ).toBe(false);
  expect(navigate).not.toHaveBeenCalled();
});
it("服务端拒绝资格时立即续验，即使客户端期限未到", async () => {
  expect(
    await renewFeishuSession(
      async () => ({
        ...context,
        eligibility_expires_at: "2026-10-09T05:00:00Z",
      }),
      { navigate: vi.fn(), force: true },
    ),
  ).toBe(true);
});
it.each(["/auth/feishu/callback", "/login?error=access_denied"])(
  "回调或错误页 %s 不循环续验",
  async (path) => {
    window.history.replaceState({}, "", path);
    expect(
      await renewFeishuSession(async () => context, { navigate: vi.fn() }),
    ).toBe(false);
  },
);
it("后台页面不跳转，回到前台可再次检查", async () => {
  const visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("hidden");
  const load = vi.fn().mockResolvedValue(context);
  expect(await renewFeishuSession(load, { navigate: vi.fn() })).toBe(false);
  expect(load).not.toHaveBeenCalled();
  visibility.mockReturnValue("visible");
  expect(await renewFeishuSession(load, { navigate: vi.fn() })).toBe(true);
});
it("网络失败或存储被禁用时留在页面", async () => {
  const navigate = vi.fn();
  expect(
    await renewFeishuSession(
      async () => {
        throw new Error("offline");
      },
      { navigate },
    ),
  ).toBe(false);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(await renewFeishuSession(async () => context, { navigate })).toBe(
    false,
  );
  expect(navigate).not.toHaveBeenCalled();
});
