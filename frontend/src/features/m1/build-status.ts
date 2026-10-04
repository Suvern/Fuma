import type { DTO } from "../../shared/api/http";
export const buildStates: Record<string, string> = {
  received: "待处理",
  verifying: "处理中",
  waiting_run: "等待 GitHub 构建",
  caching: "处理中",
  notifying: "处理中",
  succeeded: "分发成功",
  partial_success: "部分成功",
  failed: "分发失败",
  unknown: "投递结果待确认",
};
export const buildPhases: Record<string, string> = {
  verify: "核验来源",
  wait_run: "等待 GitHub 构建",
  cache: "准备安装包",
  notify: "通知投递",
};
export function currentBuildPhase(event: DTO<"BuildEvent">) {
  const stage =
    event.stages.find((s) => s.state === "running") ??
    event.stages.find((s) =>
      ["failed", "partial_success", "unknown"].includes(s.state),
    );
  if (stage) return buildPhases[stage.name];
  if (event.state === "succeeded") return "全部阶段完成";
  const next = event.stages.find((s) => s.state === "pending");
  return next ? `待${buildPhases[next.name]}` : "等待状态更新";
}
export function buildGuidance(event: DTO<"BuildEvent">) {
  if (event.state === "unknown")
    return "飞书可能已经收到消息。请先核对群消息与通知记录，结果未确认前不重复发送。";
  if (event.state === "waiting_run")
    return "回调已接收，正在等待整个 GitHub workflow 结束。不要在该 workflow 中轮询等待 Fuma。";
  if (event.state === "failed")
    return "分发未完成。查看下面失败阶段的原因，再使用可用的恢复操作。";
  if (event.state === "partial_success")
    return "部分安装包或群通知未成功，请分别检查安装包结果与通知结果。";
  if (event.state === "succeeded")
    return "安装包准备和通知投递已完成；发送成功不代表用户已阅读或安装。";
  return "Fuma 正在核验来源并准备分发，页面会自动更新。";
}
