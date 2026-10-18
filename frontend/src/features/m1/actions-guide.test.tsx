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
import { ActionsGuide, RuleConnection } from "./ActionsGuide";
import type { DTO } from "../../shared/api/http";
import example from "./github-actions-example.yml?raw";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("copies the public rule document link and a complete callback handoff without a token", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  const rule = {
    id: "22222222-2222-4222-8222-222222222222",
    repository_id: "123",
    repository_full_name: "example/mobile",
    workflow_path: ".github/workflows/build.yml",
    allowed_branches: ["main"],
    allowed_tags: ["v*"],
    asset_patterns: ["*.apk"],
    callback_url:
      "https://fuma.example/api/v1/integrations/github-actions/rule/cos-events",
  } as DTO<"ActionsRule">;
  render(
    <MemoryRouter>
      <RuleConnection rule={rule} />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: "复制文档链接给 Agent" }));
  await waitFor(() =>
    expect(writeText).toHaveBeenCalledWith(
      `${window.location.origin}/api/v1/docs/github-actions?rule_id=${rule.id}`,
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "复制完整接入说明" }));
  await waitFor(() =>
    expect(writeText).toHaveBeenLastCalledWith(
      expect.stringContaining(rule.callback_url),
    ),
  );
  expect(writeText.mock.lastCall?.[0]).toContain("Workflow：.github/workflows/build.yml");
  expect(writeText.mock.lastCall?.[0]).toContain(
    "由管理员填入 GitHub Actions Secret",
  );
  expect(
    screen
      .getByRole("link", { name: "打开此规则接入文档" })
      .getAttribute("href"),
  ).toBe(`/docs/github-actions?rule_id=${rule.id}`);
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
