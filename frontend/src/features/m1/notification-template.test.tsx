// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { ApiError, read, write, type DTO } from "../../shared/api/http";
import { NotificationTemplateSection } from "./NotificationTemplate";
vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
const config: DTO<"ReleaseNotificationTemplateConfig"> = {
  revision: 2,
  template: {
    title: "{{app_name}} 新版本",
    body: "版本 {{version}}\nBuild：{{buildNumber}}\n\n{{file_names}}",
    button_text: "立即安装",
    header_color: "blue",
  },
  defaults: {
    title: "安装包已就绪",
    body: "{{summary}}",
    button_text: "查看安装包",
    header_color: "blue",
  },
  variables: [
    { name: "app_name", label: "应用名称", sample: "Joice" },
    { name: "version", label: "版本", sample: "v1.0.0" },
    { name: "buildNumber", label: "App 构建号", sample: "42" },
    { name: "file_names", label: "安装包", sample: "Joice.apk" },
    { name: "summary", label: "结果", sample: "已就绪 1/1 个安装包" },
  ],
  sample: {
    title: "安装包已就绪",
    summary: "已就绪 1/1 个安装包",
    app_name: "Joice",
    mode: "debug",
    version_label: "v1.0.0",
    file_names: ["Joice.apk"],
    result: "success",
    occurred_at: "2026-10-07T07:42:00Z",
    page_url: null,
    button_text: "查看安装包",
    header_color: "blue",
  },
};
let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(read).mockResolvedValue(config as never);
});
afterEach(() => {
  cleanup();
  client.clear();
});
function mount() {
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationTemplateSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("previews draft variables without sending or saving and saves with revision", async () => {
  mount();
  const title = await screen.findByLabelText("卡片标题 *");
  fireEvent.change(title, { target: { value: "{{app_name}} 发布啦" } });
  expect(
    within(
      screen.getByRole("complementary", { name: "通知卡片预览" }),
    ).getByText("Joice 发布啦"),
  ).toBeTruthy();
  expect(write).not.toHaveBeenCalled();
  expect(screen.getByRole("complementary", { name: "通知卡片预览" }).textContent).toContain("Build：42");
  vi.mocked(write).mockResolvedValue({
    ...config,
    revision: 3,
    template: { ...config.template, title: "{{app_name}} 发布啦" },
  } as never);
  fireEvent.click(screen.getByRole("button", { name: "保存模板" }));
  await waitFor(() =>
    expect(write).toHaveBeenCalledWith(
      "/api/v1/settings/release-notification-template",
      "put",
      { ...config.template, title: "{{app_name}} 发布啦" },
      { revision: 2 },
    ),
  );
  expect(await screen.findByText(/模板已保存/)).toBeTruthy();
  expect(write).toHaveBeenCalledTimes(1);
});
it("rejects unknown variables locally and preserves the draft after a revision conflict", async () => {
  mount();
  const body = await screen.findByLabelText("卡片正文 *");
  fireEvent.change(body, { target: { value: "{{secret}}" } });
  fireEvent.blur(body);
  expect(
    await screen.findByText("变量无效，请使用下方列出的 {{变量名}}"),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "保存模板" }));
  expect(write).not.toHaveBeenCalled();
  fireEvent.change(body, { target: { value: "保留我的草稿" } });
  vi.mocked(write).mockRejectedValue(
    new ApiError(412, {
      code: "REVISION_MISMATCH",
      message: "数据已更新，请刷新后重试",
      retryable: false,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "保存模板" }));
  expect(await screen.findByText(/数据已更新/)).toBeTruthy();
  expect(screen.getByDisplayValue("保留我的草稿")).toBeTruthy();
});
it("restores defaults only in the draft and supports undo without a request", async () => {
  mount();
  await screen.findByLabelText("卡片正文 *");
  fireEvent.click(screen.getByRole("button", { name: "恢复默认内容" }));
  expect(screen.getByDisplayValue("{{summary}}")).toBeTruthy();
  expect(write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "撤销修改" }));
  expect((screen.getByLabelText("卡片正文 *") as HTMLTextAreaElement).value).toBe(config.template.body);
  expect(write).not.toHaveBeenCalled();
});
