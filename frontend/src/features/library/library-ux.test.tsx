// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { read, write, type DTO } from "../../shared/api/http";
import { LegacyPersistence } from "./GitHubImport";
import { PackagesPage, VersionsPage } from "./Library";
import { ReleasesPage } from "../m1/GitHub";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
vi.mock("../m1/ReleaseRules", () => ({ ReleaseRules: () => null }));
const page = { items: [], total: 0, page: 1, page_size: 20 };
const entry = {
  id: "old",
  app_id: "app",
  platform: "android",
  persistent_package_id: null,
} as DTO<"DebugEntry">;
let client: QueryClient;
let identifiers: unknown[];
let storage: unknown[];
beforeEach(() => {
  vi.resetAllMocks();
  identifiers = [];
  storage = [];
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/auth/me")
      return {
        viewer_key: "admin",
        user: { role: "admin", active: true },
      } as never;
    if (path === "/api/v1/apps/{id}")
      return { allowed_package_ids: identifiers } as never;
    if (path === "/api/v1/apps/{id}/available-storage")
      return { items: storage } as never;
    return page as never;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
});
function mount(
  element: React.ReactNode,
  path = "/admin/apps/app/versions",
  route = "/admin/apps/:id/versions",
) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("旧版迁移分别说明缺少包标识和私有云，并禁止默认或本机路径", async () => {
  storage = [
    { id: "public", name: "公开存储", provider: "cos", read_mode: "public" },
  ];
  mount(<LegacyPersistence entry={entry} />);
  fireEvent.click(screen.getByText("将旧版 Debug 分发迁入安装包库"));
  await screen.findByText(/尚无可用私有云存储/);
  expect(screen.getByText(/尚未配置 Android 的 Debug 包标识/)).toBeTruthy();
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "开始持久化迁移" })
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("combobox", { name: "原件存储位置" }));
  expect(
    screen.queryByRole("option", { name: /本机私有|系统默认|公开存储/ }),
  ).toBeNull();
  expect(write).not.toHaveBeenCalled();
});

it("有效包标识和私有云配置齐全后可选择迁移目标", async () => {
  identifiers = [
    { platform: "android", mode: "debug", identifier: "tech.example.app" },
  ];
  storage = [
    {
      id: "private",
      name: "私有云原件",
      provider: "oss",
      read_mode: "private",
    },
    { id: "public", name: "公开副本", provider: "cos", read_mode: "public" },
  ];
  mount(<LegacyPersistence entry={entry} />);
  fireEvent.click(screen.getByText("将旧版 Debug 分发迁入安装包库"));
  fireEvent.click(screen.getByRole("combobox", { name: "原件存储位置" }));
  fireEvent.click(await screen.findByRole("option", { name: /私有云原件/ }));
  await act(async () => {
    document
      .querySelectorAll(".semi-tooltip-animation-hide")
      .forEach((element) => {
        fireEvent.animationEnd(element);
        fireEvent(element, new Event("webkitAnimationEnd", { bubbles: true }));
      });
  });
  await waitFor(() =>
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "开始持久化迁移" })
        .disabled,
    ).toBe(false),
  );
  expect(write).not.toHaveBeenCalled();
});

it("版本列表先展示列表，创建按需展开并提交模式与发布说明", async () => {
  vi.mocked(write).mockResolvedValue({ id: "version" } as never);
  mount(<VersionsPage />);
  expect(screen.queryByLabelText("版本名称")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "新建版本" }));
  fireEvent.change(screen.getByRole("textbox", { name: "版本名称 *" }), {
    target: { value: "v1" },
  });
  fireEvent.change(screen.getByLabelText("发布说明"), {
    target: { value: "更新说明" },
  });
  fireEvent.click(screen.getByRole("combobox", { name: "模式" }));
  fireEvent.click(await screen.findByRole("option", { name: /Release/ }));
  fireEvent.click(screen.getByRole("button", { name: "创建版本草稿" }));
  await waitFor(() =>
    expect(write).toHaveBeenCalledWith(
      "/api/v1/apps/{id}/versions",
      "post",
      { display_name: "v1", mode: "release", release_notes: "更新说明" },
      expect.objectContaining({ id: "app" }),
    ),
  );
  await waitFor(() =>
    expect(screen.queryByRole("textbox", { name: "版本名称 *" })).toBeNull(),
  );
});

it("Release 从一个入口选择目标，旧版已导入附件只能查看而不再次创建", async () => {
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/apps/{id}/github/releases")
      return {
        ...page,
        items: [
          {
            id: "release",
            name: "Demo",
            tag_name: "v1",
            draft: false,
            prerelease: false,
            assets: [
              {
                id: "asset",
                name: "demo.apk",
                platform: "android",
                supported: true,
                size_bytes: 1,
                debug_entry_id: "old",
                cache_state: "ready",
              },
            ],
          },
        ],
      } as never;
    return page as never;
  });
  mount(
    <ReleasesPage />,
    "/admin/apps/app/releases",
    "/admin/apps/:id/releases",
  );
  expect(
    await screen.findByRole("link", { name: "已在旧版 Debug 分发 · 查看" }),
  ).toBeTruthy();
  expect(screen.queryByRole("combobox", { name: "导入目标" })).toBeNull();
  fireEvent.click(screen.getByRole("checkbox", { name: "选择 demo.apk" }));
  fireEvent.click(screen.getByRole("button", { name: "导入所选 1 个附件" }));
  expect(screen.getByRole("heading", { name: "导入安装包库" })).toBeTruthy();
  fireEvent.click(screen.getByRole("combobox", { name: "导入目标" }));
  fireEvent.click(
    await screen.findByRole("option", { name: /旧版 Debug 分发/ }),
  );
  expect(screen.getByText(/部分附件已在旧版 Debug 分发中/)).toBeTruthy();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: /导入.*个到旧版 Debug 分发/,
    }).disabled,
  ).toBe(true);
  expect(write).not.toHaveBeenCalled();
});

it("安装包读取失败提供原地重试，不把失败当作空列表", async () => {
  let failed = true;
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/apps/{id}/packages" && failed)
      throw new Error("安装包暂时不可用");
    return page as never;
  });
  mount(
    <PackagesPage />,
    "/admin/apps/app/packages",
    "/admin/apps/:id/packages",
  );
  await screen.findByText("安装包暂时不可用");
  expect(screen.queryByText(/暂无已入库安装包/)).toBeNull();
  failed = false;
  fireEvent.click(screen.getByRole("button", { name: "重试加载安装包" }));
  await screen.findByText(/暂无已入库安装包/);
  expect(screen.queryByText("安装包暂时不可用")).toBeNull();
});
