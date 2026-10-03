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
import { MemoryRouter } from "react-router";
import { read } from "../api/http";
import { RepositorySelect } from "./RepositorySelect";

vi.mock("../api/http", async (original) => ({
  ...(await original<typeof import("../api/http")>()),
  read: vi.fn(),
}));
let client: QueryClient;
const change = vi.fn();
const repo = (name: string) => ({
  id: name,
  full_name: name,
  private: true,
  default_branch: "main",
  contents_readable: true,
  actions_readable: true,
});
const page = (names: string[], total = names.length) => ({
  items: names.map(repo),
  page: 1,
  page_size: 1,
  total,
});
function mount(connectorId = "one", value = "") {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  const view = (id: string) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RepositorySelect
          key={id}
          connectorId={id}
          value={value}
          onChange={change}
        />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(view(connectorId));
  return {
    ...result,
    switchConnector: (id: string) => result.rerender(view(id)),
  };
}
beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  client?.clear();
});

describe("GitHub 仓库远程 Select", () => {
  it("未选连接时禁用且不发起请求", () => {
    mount("");
    expect(screen.getByRole("combobox").getAttribute("aria-disabled")).toBe(
      "true",
    );
    expect(read).not.toHaveBeenCalled();
  });
  it("追加下一页且选择仓库返回完整名称", async () => {
    vi.mocked(read).mockImplementation(
      async (_, options) =>
        page(
          options?.query?.page === 2 ? ["owner/second"] : ["owner/first"],
          2,
        ) as never,
    );
    mount();
    fireEvent.click(screen.getByRole("combobox"));
    await screen.findByRole("option", { name: /owner\/first/ });
    fireEvent.click(screen.getByRole("button", { name: "加载更多仓库" }));
    const second = await screen.findByRole("option", { name: /owner\/second/ });
    expect(screen.getByRole("option", { name: /owner\/first/ })).toBeTruthy();
    fireEvent.click(second);
    await waitFor(() => expect(change).toHaveBeenCalledWith("owner/second"));
  });
  it("仅发送防抖后的关键词，空结果不被旧选择遮住", async () => {
    vi.mocked(read).mockResolvedValue(page([]) as never);
    mount("one", "owner/selected");
    const select = screen.getByRole("combobox");
    fireEvent.click(select);
    fireEvent.change(within(select).getByRole("textbox"), {
      target: { value: "no" },
    });
    fireEvent.change(within(select).getByRole("textbox"), {
      target: { value: "no-match" },
    });
    await screen.findByText("没有匹配的仓库");
    const queries = vi
      .mocked(read)
      .mock.calls.map(([, options]) => options?.query?.q);
    expect(queries).toContain("no-match");
    expect(queries).not.toContain("no");
    expect(
      screen.queryByRole("option", { name: /owner\/selected/ }),
    ).toBeNull();
  });
  it("请求失败可重试，成功后清除错误", async () => {
    vi.mocked(read)
      .mockRejectedValueOnce(new Error("仓库读取失败"))
      .mockResolvedValue(page(["owner/retry"]) as never);
    mount();
    await screen.findByText("仓库读取失败");
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    await screen.findByRole("option", { name: /owner\/retry/ });
    expect(screen.queryByText("仓库读取失败")).toBeNull();
  });
  it("切换连接后忽略旧连接的迟到结果", async () => {
    let finish!: (value: never) => void;
    vi.mocked(read).mockImplementation(async (_, options) =>
      options?.id === "one"
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : (page(["new/repository"]) as never),
    );
    const view = mount();
    await waitFor(() => expect(read).toHaveBeenCalled());
    view.switchConnector("two");
    fireEvent.click(screen.getByRole("combobox"));
    await screen.findByRole("option", { name: /new\/repository/ });
    await act(async () => finish(page(["old/repository"]) as never));
    expect(
      screen.queryByRole("option", { name: /old\/repository/ }),
    ).toBeNull();
  });
});
