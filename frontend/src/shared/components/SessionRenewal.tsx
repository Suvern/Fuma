import { useEffect } from "react";
import { read } from "../api/http";
import { renewFeishuSession } from "../api/session-renewal";
import { useSession } from "../ui/common";

export function SessionRenewal() {
  const session = useSession();
  const expires = session.data?.eligibility_expires_at;
  const feishu =
    session.data?.authenticated && session.data.user?.kind === "feishu";
  useEffect(() => {
    if (!feishu || !expires || !session.isSuccess || session.isFetching) return;
    const expiry = Date.parse(expires);
    if (!Number.isFinite(expiry)) return;
    const check = () => {
      if (Date.now() >= expiry && document.visibilityState !== "hidden")
        void renewFeishuSession(() => read("/api/v1/auth/browser-context"));
    };
    const timer = window.setTimeout(
      check,
      Math.max(0, expiry - Date.now() + 100),
    );
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, [feishu, expires, session.isSuccess, session.isFetching]);
  return null;
}
