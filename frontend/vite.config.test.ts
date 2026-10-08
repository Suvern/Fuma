import { beforeEach, describe, expect, it, vi } from "vitest";

const { loadEnv } = vi.hoisted(() => ({ loadEnv: vi.fn(() => ({})) }));
vi.mock("vite", async (importOriginal) => ({
  ...(await importOriginal<typeof import("vite")>()),
  loadEnv,
}));

import viteConfig from "./vite.config";

describe("development proxy configuration", () => {
  beforeEach(() => {
    loadEnv.mockReset();
    loadEnv.mockReturnValue({});
  });

  it("defaults to the local API and keeps local variables out of browser env", () => {
    const config = viteConfig({ command: "serve", mode: "development" });
    expect(config.server.proxy["/api"].target).toBe("http://127.0.0.1:8000");
    expect(config.server.proxy["/api"].changeOrigin).toBe(false);
    expect(config.envDir).toBe(false);
    expect(loadEnv).toHaveBeenCalledWith(
      "development",
      expect.stringMatching(/\/frontend\/$/),
      "FUMA_API_PROXY_TARGET",
    );
  });

  it("uses the configured remote origin without exposing it through client env", () => {
    loadEnv.mockReturnValue({ FUMA_API_PROXY_TARGET: " https://fuma.example.com " });
    const config = viteConfig({ command: "serve", mode: "development" });
    expect(config.server.proxy["/api"].target).toBe("https://fuma.example.com");
    expect(config.server.proxy["/api"].changeOrigin).toBe(true);
    expect(config.envDir).toBe(false);
  });

  it.each([
    { command: "serve" as const, mode: "local-backend" },
    { command: "serve" as const, mode: "test" },
    { command: "build" as const, mode: "production" },
    { command: "serve" as const, mode: "production", isPreview: true },
  ])("does not load local configuration for $command / $mode", (env) => {
    const config = viteConfig(env);
    expect(loadEnv).not.toHaveBeenCalled();
    expect(config.server.proxy["/api"].target).toBe("http://127.0.0.1:8000");
  });

  it.each([
    "not-a-url",
    "ftp://fuma.example.com",
    "https://user:password@fuma.example.com",
    "https://fuma.example.com/api",
    "https://fuma.example.com?token=example",
    "https://fuma.example.com#fragment",
  ])("rejects invalid proxy origins without echoing the input", (target) => {
    loadEnv.mockReturnValue({ FUMA_API_PROXY_TARGET: target });
    expect(() => viteConfig({ command: "serve", mode: "development" })).toThrow(
      /^FUMA_API_PROXY_TARGET must be an HTTP\(S\) origin/,
    );
    try {
      viteConfig({ command: "serve", mode: "development" });
    } catch (error) {
      expect((error as Error).message).not.toContain(target);
    }
  });
});
