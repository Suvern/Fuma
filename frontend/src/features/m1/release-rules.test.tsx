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
import { MemoryRouter } from "react-router";
import { read, write } from "../../shared/api/http";
import { ReleaseRules } from "./ReleaseRules";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
let queryClient: QueryClient;
const rules = {
  asset_patterns: ["*.apk", "*.ipa"],
  exclude_patterns: [],
  tag_pattern: "*",
  prerelease: "all",
};
const policy = {
  rules,
  auto_enabled: false,
  interval_minutes: 15,
  revision: 2,
  next_check_at: null,
  last_task_id: null,
  last_result: null,
  status: "disabled",
};
const preview = {
  snapshot_token: "a".repeat(64),
  synced_at: "2026-10-04T01:00:00Z",
  matched_count: 203,
  new_count: 202,
  existing_count: 1,
  skipped_count: 8,
  truncated: true,
  items: [
    {
      release_id: "1",
      tag_name: "v1.2",
      asset_id: "10",
      file_name: "joice-arm64.apk",
      platform: "android",
      size_bytes: 1024,
      existing: false,
    },
  ],
};
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/apps/{id}/github/releases/policy")
      return policy as never;
    if (path === "/api/v1/tasks/{id}")
      return { id: "task", state: "succeeded" } as never;
    throw Error("Unexpected request");
  });
  vi.mocked(write).mockImplementation(async (path) => {
    if (path.endsWith("/preview")) return preview as never;
    if (path.endsWith("/policy")) return policy as never;
    return { task_id: "task", status_url: "/api/v1/tasks/task" } as never;
  });
});
afterEach(() => {
  cleanup();
  queryClient.clear();
});
function mount(ready = true) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReleaseRules appId="app" snapshotReady={ready} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("previews glob rules across all releases and imports the entire preview", async () => {
  mount();
  fireEvent.change(await screen.findByLabelText(/安装包文件名/), {
    target: { value: "joice-*.apk, *.ipa" },
  });
  fireEvent.change(screen.getByLabelText("排除文件名（可选）"), {
    target: { value: "*unsigned*" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览匹配产物" }));
  const button = await screen.findByRole("button", {
    name: "批量导入 202 个安装包",
  });
  expect(screen.getByText(/仅展示前 200 个匹配产物/)).toBeTruthy();
  expect(screen.getByText("joice-arm64.apk")).toBeTruthy();
  fireEvent.click(button);
  await waitFor(() =>
    expect(write).toHaveBeenCalledWith(
      "/api/v1/apps/{id}/github/releases/import",
      "post",
      {
        rules: {
          ...rules,
          asset_patterns: ["joice-*.apk", "*.ipa"],
          exclude_patterns: ["*unsigned*"],
        },
        snapshot_token: preview.snapshot_token,
      },
      { id: "app", key: expect.any(String) },
    ),
  );
});
it("invalidates a preview when the matching rules are edited", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "预览匹配产物" }));
  await screen.findByRole("button", { name: "批量导入 202 个安装包" });
  fireEvent.change(screen.getByLabelText(/Release Tag/), {
    target: { value: "v2*" },
  });
  expect(screen.queryByRole("button", { name: /批量导入/ })).toBeNull();
});
it("saves opt-in polling independently of having a local snapshot", async () => {
  mount(false);
  const checkbox = await screen.findByRole("checkbox", {
    name: "自动检查更新并导入匹配产物",
  });
  expect((checkbox as HTMLInputElement).checked).toBe(false);
  expect(
    (screen.getByRole("button", { name: "预览匹配产物" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(checkbox);
  fireEvent.change(screen.getByLabelText(/检查间隔/), {
    target: { value: "5" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "保存规则并启用自动同步" }),
  );
  await waitFor(() =>
    expect(write).toHaveBeenCalledWith(
      "/api/v1/apps/{id}/github/releases/policy",
      "put",
      { rules, auto_enabled: true, interval_minutes: 5 },
      { id: "app", revision: 2 },
    ),
  );
});
