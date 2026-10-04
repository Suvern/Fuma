import type { DTO } from "../../shared/api/http";

export const roleNames = {
  admin: "管理员",
  maintainer: "应用维护者",
  downloader: "仅下载用户",
} as const;
export function canManage(user?: DTO<"SessionUser"> | null) {
  return (
    !!user &&
    user.active !== false &&
    ["admin", "maintainer"].includes(user.role)
  );
}
export function isGlobalAdmin(user?: DTO<"SessionUser"> | null) {
  return user?.role === "admin" && user.active !== false;
}
export function globalOnlyPath(pathname: string) {
  return [
    "/admin/connectors",
    "/admin/settings/feishu",
    "/admin/settings/cache",
    "/admin/settings/storage",
    "/admin/settings/members",
  ].some((path) => pathname === path || pathname.startsWith(`${path}/`));
}
