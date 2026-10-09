import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router";
import { read, safeReturnPath, ssoUrl } from "../../shared/api/http";

import { claimAutomaticAttempt, isFeishuBrowser, suppressAutomaticFeishuLogin } from "./feishu-auto-login";

const navigateToSso = (url: string) => window.location.replace(url);

export function FeishuAutoLogin({
  sessionReady,
  authenticated,
  navigate = navigateToSso,
}: {
  sessionReady: boolean;
  authenticated: boolean;
  navigate?: (url: string) => void;
}) {
  const location = useLocation();
  const inFeishu = isFeishuBrowser(navigator.userAgent);
  const status = useQuery({
    queryKey: ["bootstrap"],
    queryFn: () => read("/api/v1/auth/bootstrap-status"),
    enabled: inFeishu && sessionReady && !authenticated,
  });
  useEffect(() => {
    if (!inFeishu || !sessionReady || authenticated) return;
    const params = new URLSearchParams(location.search);
    if (params.has("error") || location.pathname === "/auth/error") {
      suppressAutomaticFeishuLogin();
      return;
    }
    if (!/^\/(?:$|login\/?$|(?:apps|debug|releases)(?:\/|$))/.test(location.pathname)) return;
    if (!status.isSuccess || status.isFetching || !status.data.initialized || !status.data.sso_enabled) return;
    // Store before leaving the page so refresh, Back and failed callbacks cannot
    // cause a loop. Closing the webview/tab starts a new automatic-login attempt.
    if (!claimAutomaticAttempt()) return;
    const returnTo = location.pathname === "/login"
      ? safeReturnPath(params.get("return_to") ?? "/admin")
      : location.pathname + location.search + location.hash;
    navigate(ssoUrl(returnTo));
  }, [inFeishu, sessionReady, authenticated, location, status.isSuccess, status.isFetching, status.data, navigate]);
  return null;
}
