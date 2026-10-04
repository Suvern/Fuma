import { expect, it } from "vitest";
import type { DTO } from "../../shared/api/http";
import { currentBuildPhase, buildGuidance } from "./build-status";

it("shows the running notification after some packages failed", () => {
  const event = {
    state: "notifying",
    stages: [
      { name: "verify", state: "succeeded" },
      { name: "wait_run", state: "succeeded" },
      { name: "cache", state: "partial_success" },
      { name: "notify", state: "running" },
    ],
  } as DTO<"BuildEvent">;
  expect(currentBuildPhase(event)).toBe("通知投递");
});

it("separates unknown delivery from failure and waiting from completion", () => {
  expect(buildGuidance({ state: "unknown" } as DTO<"BuildEvent">)).toContain(
    "不重复发送",
  );
  expect(
    buildGuidance({ state: "waiting_run" } as DTO<"BuildEvent">),
  ).toContain("不要在该 workflow 中轮询");
  expect(
    currentBuildPhase({
      state: "succeeded",
      stages: [],
    } as unknown as DTO<"BuildEvent">),
  ).toBe("全部阶段完成");
});
