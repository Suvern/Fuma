import type { DTO } from "./http";

const renewalKey = "fuma:feishu-renewal:v1";
let pending: Promise<boolean> | undefined;
const isHidden = () => document.visibilityState === "hidden";

/** Refresh identity through OAuth; never extend server eligibility locally. */
export function renewFeishuSession(
  loadContext: () => Promise<DTO<"BrowserContext">>,
  {
    force = false,
    navigate = (url: string) => window.location.replace(url),
  } = {},
): Promise<boolean> {
  if (pending) return pending;
  pending = (async () => {
    if (typeof window === "undefined" || isHidden()) return false;
    const url = new URL(window.location.href);
    if (url.pathname.startsWith("/auth/") || url.searchParams.has("error"))
      return false;
    try {
      const context = await loadContext();
      if (isHidden()) return false;
      if (
        !context.authenticated ||
        context.user?.kind !== "feishu" ||
        context.user.active === false
      )
        return false;
      const expires = Date.parse(context.eligibility_expires_at ?? "");
      if (!force && (!Number.isFinite(expires) || expires > Date.now()))
        return false;
      // One automatic attempt per session. OAuth success creates a new viewer key;
      // cancellation retains this key and therefore cannot trigger a redirect loop.
      const previous = JSON.parse(
        sessionStorage.getItem(renewalKey) ?? "null",
      ) as { viewer: string; at: number } | null;
      if (
        previous &&
        (previous.viewer === context.viewer_key ||
          Date.now() - previous.at < 60_000)
      )
        return false;
      sessionStorage.setItem(
        renewalKey,
        JSON.stringify({ viewer: context.viewer_key, at: Date.now() }),
      );
      const returnTo = url.pathname + url.search + url.hash;
      navigate(
        `/api/v1/auth/feishu/start?return_to=${encodeURIComponent(returnTo)}`,
      );
      return true;
    } catch {
      // Network/storage failures leave the existing manual verification link usable.
      return false;
    }
  })().finally(() => {
    pending = undefined;
  });
  return pending;
}
