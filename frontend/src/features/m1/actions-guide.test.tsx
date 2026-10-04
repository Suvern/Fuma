// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { ActionsGuide } from "./ActionsGuide";
import example from "./github-actions-example.yml?raw";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("copies the maintained workflow and documents the full integration before rule creation", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  render(
    <MemoryRouter>
      <ActionsGuide appId="demo" />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("heading", { name: "接入 GitHub Actions" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByText("复制 build YAML 示例与修改说明"));
  fireEvent.click(screen.getByRole("button", { name: "复制完整 YAML" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(example));
  expect(example).toContain("${{ secrets.FUMA_CI_TOKEN }}");
  expect(example).not.toContain("FUMA_ACTIONS_TOKEN");
  expect(screen.getByText(/仅保存令牌不会触发通知/)).toBeTruthy();
});

it("keeps the YAML selectable when clipboard access fails", async () => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
  });
  render(
    <MemoryRouter>
      <ActionsGuide appId="demo" />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByText("复制 build YAML 示例与修改说明"));
  fireEvent.click(screen.getByRole("button", { name: "复制完整 YAML" }));
  expect(
    await screen.findByText("无法自动复制，请选择下方内容后手动复制。"),
  ).toBeTruthy();
  expect(screen.getByLabelText("GitHub Actions YAML 示例").textContent).toBe(
    example,
  );
});
