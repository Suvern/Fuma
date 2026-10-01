import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { ApiError, read, safeReturnPath, write } from "./http";
afterEach(() => vi.restoreAllMocks());
describe("契约请求边界", () => {
  it("写请求先获取浏览器上下文，附加 CSRF、版本和幂等标识", async () => {
    const request = vi.spyOn(api, "request");
    request.mockResolvedValueOnce({
      data: { csrf_token: "test-csrf" },
      response: new Response("{}"),
    } as never);
    request.mockResolvedValueOnce({
      data: { enabled: false },
      response: new Response("{}"),
    } as never);
    await write(
      "/api/v1/debug-entries/{id}",
      "patch",
      { enabled: false },
      { id: "entry", revision: 7, key: "intent-key" },
    );
    expect(request.mock.calls[0]?.slice(0, 2)).toEqual([
      "get",
      "/api/v1/auth/browser-context",
    ]);
    expect(request.mock.calls[1]?.[2]).toMatchObject({
      params: {
        path: { id: "entry" },
        header: {
          "X-CSRF-Token": "test-csrf",
          "If-Match": '"7"',
          "Idempotency-Key": "intent-key",
        },
      },
      body: { enabled: false },
    });
  });
  it("标准错误保留 code 和 request ID", async () => {
    vi.spyOn(api, "request").mockResolvedValue({
      error: {
        error: {
          code: "REVISION_MISMATCH",
          message: "版本冲突",
          retryable: false,
        },
        request_id: "request-1",
      },
      response: new Response("{}", { status: 412 }),
    } as never);
    await expect(read("/api/v1/apps")).rejects.toMatchObject({
      status: 412,
      requestId: "request-1",
      message: "版本冲突",
    });
  });
  it("CSRF上下文读取失败时不发送写请求", async () => {
    const request = vi.spyOn(api, "request").mockResolvedValue({
      response: new Response("{}", { status: 503 }),
    } as never);
    await expect(
      write("/api/v1/auth/logout", "post", undefined),
    ).rejects.toBeInstanceOf(ApiError);
    expect(request).toHaveBeenCalledTimes(1);
  });
  it.each([
    "https://external.test",
    "//external.test",
    "/\\external.test",
    "javascript:alert(1)",
    "/\n/external.test",
  ])("拒绝非站内 return_to %s", (value) => {
    expect(safeReturnPath(value)).toBe("/");
  });
  it("保留站内深链返回地址", () => {
    expect(safeReturnPath("/debug/entry?view=detail")).toBe(
      "/debug/entry?view=detail",
    );
  });
});
