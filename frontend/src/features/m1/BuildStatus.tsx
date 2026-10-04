import Tag from "@douyinfe/semi-ui-19/lib/es/tag";
import { buildStates } from "./build-status";

export function BuildResult({ state }: { state: string }) {
  const color =
    state === "succeeded"
      ? "green"
      : state === "failed"
        ? "red"
        : ["partial_success", "unknown"].includes(state)
          ? "orange"
          : state === "received"
            ? "grey"
            : "blue";
  return <Tag color={color}>{buildStates[state] ?? state}</Tag>;
}
