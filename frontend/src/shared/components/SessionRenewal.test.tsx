// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { useSession } from "../ui/common";
import { renewFeishuSession } from "../api/session-renewal";
import { SessionRenewal } from "./SessionRenewal";
vi.mock("../ui/common", () => ({ useSession: vi.fn() }));
vi.mock("../api/session-renewal", () => ({
  renewFeishuSession: vi.fn().mockResolvedValue(true),
}));
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-09T04:00:00Z"));
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.mocked(useSession).mockReturnValue({
    isSuccess: true,
    isFetching: false,
    data: {
      authenticated: true,
      user: { kind: "feishu" },
      eligibility_expires_at: "2026-10-09T04:05:00Z",
    },
  } as ReturnType<typeof useSession>);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});
it("资格到期时自动续验", async () => {
  render(<SessionRenewal />);
  await act(() => vi.advanceTimersByTimeAsync(299_000));
  expect(renewFeishuSession).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(1_200));
  expect(renewFeishuSession).toHaveBeenCalledTimes(1);
});
it("后台到期不打断用户，恢复前台再续验", async () => {
  const visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("hidden");
  render(<SessionRenewal />);
  await act(() => vi.advanceTimersByTimeAsync(300_200));
  expect(renewFeishuSession).not.toHaveBeenCalled();
  visibility.mockReturnValue("visible");
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  expect(renewFeishuSession).toHaveBeenCalledTimes(1);
});
