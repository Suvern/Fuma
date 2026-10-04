// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { read, write } from "../../shared/api/http";
import { PackagesPage, PublishedReleasesPage, VersionPage } from "./Library";

vi.mock("../../shared/api/http", async (original) => ({
  ...(await original<typeof import("../../shared/api/http")>()),
  read: vi.fn(),
  write: vi.fn(),
}));
let client: QueryClient;
const page = { items: [], total: 0, page: 1, page_size: 20 };
function mount(element: React.ReactNode, path: string, route: string) {
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
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
});

it("retains an upload intent key after an ambiguous create failure", async () => {
  vi.mocked(read).mockResolvedValue(page as never);
  vi.mocked(write).mockRejectedValue(new Error("网络中断"));
  mount(
    <PackagesPage />,
    "/admin/apps/app/packages",
    "/admin/apps/:id/packages",
  );
  const file = new File(["fixture"], "test.apk");
  fireEvent.change(screen.getByLabelText("选择安装包"), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByRole("button", { name: "开始上传" }));
  await screen.findByText("网络中断");
  const key = vi.mocked(write).mock.calls[0]?.[3]?.key;
  expect(key).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "开始上传" }));
  await waitFor(() => expect(write).toHaveBeenCalledTimes(2));
  expect(vi.mocked(write).mock.calls[1]?.[3]?.key).toBe(key);
});

it("shows reclaim failure and offers reclaim retry without exposing republish", async () => {
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/versions/{id}")
      return {
        id: "version",
        app_id: "app",
        display_name: "Demo",
        mode: "release",
        release_notes: "",
        revision: 1,
        created_at: "2026-10-04T00:00:00Z",
      } as never;
    if (path === "/api/v1/versions/{id}/publications")
      return {
        ...page,
        items: [
          {
            id: "pub",
            app_id: "app",
            version_id: "version",
            platform: "android",
            mode: "release",
            state: "unpublished",
            revision: 7,
            package_ids: ["package"],
            file_set_frozen: true,
            public_storage_id: "cloud",
            access_state: "reclaim_failed",
            access_error: "源站删除未确认",
            access_task_id: "task",
          },
        ],
      } as never;
    return page as never;
  });
  mount(<VersionPage />, "/admin/versions/version", "/admin/versions/:id");
  await screen.findByText("源站删除未确认");
  expect(screen.getByRole("button", { name: "重试访问收回" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "发布" })).toBeNull();
  expect(screen.queryByRole("button", { name: "归档" })).toBeNull();
});

it("refreshes the package list when a polled upload becomes ready", async () => {
  let ready = false;
  const upload = {
    id: "upload",
    file_name: "uploaded.ipa",
    state: "processing",
    parts: [],
    expected_parts: 1,
  };
  vi.mocked(read).mockImplementation(async (path) => {
    if (path === "/api/v1/apps/{id}/uploads")
      return { ...page, items: [upload] } as never;
    if (path === "/api/v1/apps/{id}/packages")
      return {
        ...page,
        items: ready
          ? [
              {
                id: "package",
                file_name: "Ready package.ipa",
                platform: "ios",
                mode: "release",
                version_name: "1.0",
                build_number: "1",
                package_identifier: "com.example.app",
                size_bytes: 100,
                created_at: "2026-10-04T00:00:00Z",
                signature_status: "unverified",
                source_kind: "upload",
                state: "ready",
                sha256: "a".repeat(64),
                architectures: [],
                signer_fingerprints: [],
                parser_version: "test",
                internal_notes: "",
                revision: 1,
              },
            ]
          : [],
      } as never;
    return page as never;
  });
  mount(
    <PackagesPage />,
    "/admin/apps/app/packages",
    "/admin/apps/:id/packages",
  );
  await screen.findByText("暂无已入库安装包。上传后请等待解析任务完成。");
  ready = true;
  await act(async () => {
    client.setQueryData(["library-uploads", "app", 1], {
      ...page,
      items: [{ ...upload, state: "ready" }],
    });
  });
  expect(
    await screen.findByRole("heading", { name: "Ready package.ipa" }),
  ).toBeTruthy();
});

it("submits separate app and version catalog filters and clears them", async () => {
  vi.mocked(read).mockResolvedValue(page as never);
  mount(<PublishedReleasesPage />, "/releases", "/releases");
  fireEvent.change(screen.getByLabelText("应用名称"), {
    target: { value: "Mobile" },
  });
  fireEvent.change(screen.getByLabelText("版本名称"), {
    target: { value: "2.0" },
  });
  fireEvent.click(screen.getByRole("button", { name: "应用筛选" }));
  await waitFor(() =>
    expect(read).toHaveBeenCalledWith("/api/v1/catalog/publications", {
      query: expect.objectContaining({
        app_name: "Mobile",
        version_name: "2.0",
        page: 1,
      }),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));
  expect((screen.getByLabelText("应用名称") as HTMLInputElement).value).toBe(
    "",
  );
  expect((screen.getByLabelText("版本名称") as HTMLInputElement).value).toBe(
    "",
  );
});
