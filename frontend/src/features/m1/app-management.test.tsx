// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { ApiError, read, write, type DTO } from "../../shared/api/http";
import { ErrorBox, size } from "../../shared/ui/common";
import { AppPage, AppsPage } from "./Apps";
import { ActionsPage } from "./Actions";
import { DebugListPage } from "./Debug";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));

const app: DTO<"App"> = {
  id: "app",
  name: "QA 应用",
  public_slug: "qa-app",
  description: "原描述",
  platforms: ["android"],
  enabled: false,
  revision: 1,
  debug_entry_count: 0,
  allowed_package_ids: [],
  created_at: "2026-10-02T00:00:00Z",
  updated_at: "2026-10-02T00:00:00Z",
  repository: {
    connector_id: "connector",
    repository_id: "1",
    full_name: "owner/repo",
    private: false,
  },
};
let client: QueryClient;
let server: DTO<"App">;
const page = { items: [], page: 1, page_size: 20, total: 0 };
function mount(
  element: React.ReactNode,
  route = "/admin/apps/:id",
  path = "/admin/apps/app",
) {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
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
beforeEach(() => {
  vi.resetAllMocks();
  server = structuredClone(app);
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
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/apps/{id}") return server as never;
    if (path === "/api/v1/connectors/github")
      return {
        ...page,
        items: [{ id: "connector", name: "default", enabled: true }],
        total: 1,
      } as never;
    return page as never;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
});

describe("应用管理走查问题回归", () => {
  it("包标识按平台和模式提交，未配置模式可保存", async () => {
    vi.mocked(write).mockImplementation(async (_path, _method, body) => {
      server = {
        ...server,
        ...(body as DTO<"AppUpdate">),
        revision: 2,
      } as DTO<"App">;
      return server as never;
    });
    mount(<AppPage />);
    fireEvent.change(await screen.findByLabelText("Android Debug 包名"), {
      target: { value: "com.example.debug, com.example.qa" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByText("基本信息已保存。");
    expect(server.allowed_package_ids).toEqual([
      { platform: "android", mode: "debug", identifier: "com.example.debug" },
      { platform: "android", mode: "debug", identifier: "com.example.qa" },
    ]);
    expect(
      (screen.getByLabelText("Android Release 包名") as HTMLInputElement).value,
    ).toBe("");
  });

  it("移除平台失败后保留包标识草稿与错误原因", async () => {
    server = {
      ...server,
      platforms: ["android", "ios"],
      allowed_package_ids: [
        { platform: "ios", mode: "release", identifier: "com.Example.App" },
      ],
    };
    vi.mocked(write).mockRejectedValue(
      new ApiError(409, {
        code: "PLATFORM_IN_USE",
        message: "iOS 仍有关联安装包",
        retryable: false,
      }),
    );
    mount(<AppPage />);
    fireEvent.change(await screen.findByLabelText("Android Debug 包名"), {
      target: { value: "com.example.draft" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "iOS" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByText("iOS 仍有关联安装包");
    expect(
      (screen.getByLabelText("Android Debug 包名") as HTMLInputElement).value,
    ).toBe("com.example.draft");
    expect(vi.mocked(write).mock.calls.at(-1)?.[2]).toEqual(
      expect.objectContaining({
        platforms: ["android"],
        allowed_package_ids: [
          {
            platform: "android",
            mode: "debug",
            identifier: "com.example.draft",
          },
        ],
      }),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "iOS" }));
    expect(
      (screen.getByLabelText("iOS Release Bundle ID") as HTMLInputElement)
        .value,
    ).toBe("com.Example.App");
  });

  it("创建时动态显示各端包标识，不提交未选择端的草稿", async () => {
    vi.mocked(write).mockRejectedValue(new Error("创建失败"));
    mount(<AppsPage />, "/admin/apps", "/admin/apps?new=1");
    fireEvent.change(await screen.findByLabelText(/应用名称/), {
      target: { value: "新应用" },
    });
    fireEvent.change(screen.getByLabelText(/分发标识/), {
      target: { value: "new-app" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "iOS" }));
    fireEvent.change(screen.getByLabelText("iOS Release Bundle ID"), {
      target: { value: "com.example.app" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "iOS" }));
    fireEvent.click(screen.getByRole("button", { name: "创建应用" }));
    await screen.findByText("创建失败");
    expect(vi.mocked(write).mock.calls.at(-1)?.[2]).toEqual(
      expect.objectContaining({
        platforms: ["android"],
        allowed_package_ids: [],
      }),
    );
  });

  it("URL 还原组合筛选，清空筛选同时回到第一页", async () => {
    mount(
      <AppsPage />,
      "/admin/apps",
      "/admin/apps?q=com.example&platform=ios&enabled=false&page=3",
    );
    await screen.findByText("没有匹配的应用");
    expect(read).toHaveBeenCalledWith(
      "/api/v1/apps",
      expect.objectContaining({
        query: { page: 3, q: "com.example", platform: "ios", enabled: false },
      }),
    );
    expect((screen.getByLabelText("关键词") as HTMLInputElement).value).toBe(
      "com.example",
    );
    fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));
    await screen.findByText("添加你的第一个应用");
    expect(read).toHaveBeenCalledWith(
      "/api/v1/apps",
      expect.objectContaining({
        query: { page: 1, q: "", platform: undefined, enabled: undefined },
      }),
    );
  });

  it.each([
    ["Android Debug 包名", "com.1bad", "com.example.app, com.example.qa"],
    ["iOS Release Bundle ID", "com.example.*", "com.Example.my-app"],
  ])("%s 的可选多标识校验支持 HTML v 模式", async (label, invalid, valid) => {
    server = { ...server, platforms: ["android", "ios"] };
    mount(<AppPage />);
    const field = (await screen.findByLabelText(label)) as HTMLInputElement;
    const pattern = new RegExp(`^(?:${field.pattern})$`, "v");
    expect(pattern.test(invalid)).toBe(false);
    expect(pattern.test(valid)).toBe(true);
    expect(pattern.test("")).toBe(true);
    fireEvent.change(field, { target: { value: invalid } });
    expect(field.validity.patternMismatch).toBe(true);
  });

  it("仓库更新保留草稿，随后保存使用新版本且保留成功反馈", async () => {
    vi.mocked(write).mockImplementation(async (path, _method, body) => {
      if (path === "/api/v1/apps/{id}/repository")
        server = { ...server, revision: 2 };
      if (path === "/api/v1/apps/{id}")
        server = {
          ...server,
          ...(body as DTO<"AppUpdate">),
          revision: 3,
        } as DTO<"App">;
      return server as never;
    });
    mount(<AppPage />);
    const description = await screen.findByLabelText("描述");
    fireEvent.change(description, { target: { value: "未保存草稿" } });
    fireEvent.change(screen.getByLabelText(/仓库完整名称/), {
      target: { value: "owner/repo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "验证并绑定" }));
    await screen.findByText("仓库绑定已保存。");
    await waitFor(() =>
      expect(client.getQueryData<DTO<"App">>(["app", "app"])?.revision).toBe(2),
    );
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "未保存草稿",
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByText("基本信息已保存。");
    expect(vi.mocked(write).mock.calls.at(-1)?.[3]).toEqual({
      id: "app",
      revision: 2,
    });
    expect(server.description).toBe("未保存草稿");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "保存" }).hasAttribute("disabled"),
      ).toBe(false),
    );
  });

  it("后台刷新遇到他人修改时保留草稿及原版本，仍由服务端拒绝覆盖", async () => {
    vi.mocked(write).mockRejectedValue(
      new ApiError(412, {
        code: "REVISION_MISMATCH",
        message: "数据已更新，请刷新后重试",
        retryable: false,
      }),
    );
    mount(<AppPage />);
    fireEvent.change(await screen.findByLabelText("描述"), {
      target: { value: "我的草稿" },
    });
    await act(async () => {
      client.setQueryData(["app", "app"], {
        ...app,
        description: "他人修改",
        revision: 2,
      });
    });
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "我的草稿",
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByText("数据已更新，请刷新后重试");
    expect(vi.mocked(write).mock.calls[0]?.[3]).toEqual({
      id: "app",
      revision: 1,
    });
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "我的草稿",
    );
  });

  it("没有草稿时刷新会显示最新基本信息", async () => {
    mount(<AppPage />);
    await screen.findByLabelText("描述");
    await act(async () => {
      client.setQueryData(["app", "app"], {
        ...app,
        description: "新描述",
        revision: 2,
      });
    });
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "新描述",
    );
  });

  it("关闭失败的新建表单后，重新打开不显示旧错误", async () => {
    vi.mocked(write).mockRejectedValue(
      new ApiError(409, {
        code: "APP_SLUG_EXISTS",
        message: "App 路径已被使用",
        retryable: false,
      }),
    );
    mount(<AppsPage />, "/admin/apps", "/admin/apps");
    fireEvent.click(screen.getAllByRole("button", { name: "新建应用" })[0]!);
    fireEvent.change(screen.getByLabelText(/应用名称/), {
      target: { value: "QA" },
    });
    fireEvent.change(screen.getByLabelText(/分发标识/), {
      target: { value: "qa-app" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建应用" }));
    await screen.findByText("App 路径已被使用");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getAllByRole("button", { name: "新建应用" })[0]!);
    expect(screen.queryByText("App 路径已被使用")).toBeNull();
    expect((screen.getByLabelText(/应用名称/) as HTMLInputElement).value).toBe(
      "",
    );
  });

  it("平台全部取消时在本地阻止提交，选择 iOS 后恢复", async () => {
    mount(<AppsPage />, "/admin/apps", "/admin/apps?new=1");
    fireEvent.change(screen.getByLabelText(/应用名称/), {
      target: { value: "QA" },
    });
    fireEvent.change(screen.getByLabelText(/分发标识/), {
      target: { value: "qa-app" },
    });
    fireEvent.click(screen.getByLabelText("Android"));
    fireEvent.click(screen.getByRole("button", { name: "创建应用" }));
    expect(write).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(
      "请至少选择一个支持平台。",
    );
    fireEvent.click(screen.getByLabelText("iOS"));
    expect(
      (screen.getByLabelText("Android") as HTMLInputElement).validity.valid,
    ).toBe(true);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    [
      "slug",
      <AppsPage />,
      "/admin/apps",
      "/admin/apps?new=1",
      /分发标识/,
      "Invalid_slug",
      "qa-app",
    ],
    [
      "repository",
      <AppPage />,
      "/admin/apps/:id",
      "/admin/apps/app",
      /仓库完整名称/,
      "invalid name",
      "owner/repo-name",
    ],
    [
      "workflow",
      <ActionsPage />,
      "/admin/apps/:id/actions",
      "/admin/apps/app/actions",
      /Workflow 路径/,
      "invalid.yml",
      ".github/workflows/build.yaml",
    ],
  ] as const)(
    "%s 使用可编译的 pattern 且能拦截非法值",
    async (_name, element, route, path, label, invalid, valid) => {
      mount(element, route, path);
      const field = (await screen.findByLabelText(label)) as HTMLInputElement;
      const pattern = new RegExp(`^(?:${field.pattern})$`, "v");
      expect(pattern.test(invalid)).toBe(false);
      expect(pattern.test(valid)).toBe(true);
      fireEvent.change(field, { target: { value: invalid } });
      expect(field.validity.patternMismatch).toBe(true);
      fireEvent.change(field, { target: { value: valid } });
      expect(field.validity.valid).toBe(true);
    },
  );

  it("仓库请求中显示加载，零结果给出检索提示", async () => {
    let finish: (value: never) => void = () => {};
    const original = vi.mocked(read).getMockImplementation()!;
    vi.mocked(read).mockImplementation((path, options) =>
      path === "/api/v1/connectors/github/{id}/repositories"
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : original(path, options),
    );
    mount(<AppPage />);
    await screen.findByLabelText("描述");
    expect(screen.getByText("正在搜索仓库…")).toBeTruthy();
    const select = screen.getByRole("combobox", { name: "GitHub 仓库" });
    fireEvent.click(select);
    fireEvent.change(within(select).getByRole("textbox"), {
      target: { value: "no-match" },
    });
    await waitFor(() =>
      expect(read).toHaveBeenCalledWith(
        "/api/v1/connectors/github/{id}/repositories",
        expect.objectContaining({ query: { q: "no-match", page: 1 } }),
      ),
    );
    await act(async () => {
      finish(page as never);
    });
    await screen.findByText("没有匹配的仓库");
    expect(screen.queryByText("正在搜索仓库…")).toBeNull();
  });

  it("Debug 搜索空结果不再误导用户导入安装包", async () => {
    mount(<DebugListPage />, "/admin/apps/:id/debug", "/admin/apps/app/debug");
    await screen.findByText("暂无 Debug 条目");
    fireEvent.change(screen.getByLabelText("关键词"), {
      target: { value: "no-match" },
    });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    await screen.findByText("没有匹配的 Debug 包");
    expect(screen.queryByText("请从 Release 选择安装包。")).toBeNull();
  });

  it("服务端字段错误使用可操作的文案而不暴露内部字段路径", () => {
    render(
      <ErrorBox
        error={
          new ApiError(422, {
            code: "VALIDATION_ERROR",
            message: "请求参数不合法",
            retryable: false,
            field_errors: [
              { field: "body.platforms", message: "字段格式或取值不合法" },
            ],
          })
        }
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "请至少选择一个支持平台。",
    );
    expect(screen.getByRole("alert").textContent).not.toContain(
      "body.platforms",
    );
  });
  it.each([
    [0, "0 B"],
    [50, "50 B"],
    [1023, "1023 B"],
    [1024, "1.0 KB"],
    [1048576, "1.0 MB"],
    [1073741824, "1.00 GB"],
  ])("大小 %i 显示为 %s", (bytes, expected) => {
    expect(size(bytes as number)).toBe(expected);
  });
});
