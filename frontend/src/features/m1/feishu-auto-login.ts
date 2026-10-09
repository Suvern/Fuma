const attemptKey = "fuma:feishu-auto-login:v1";

export function isFeishuBrowser(userAgent: string) {
  // This is a UX hint only. The server still validates OAuth state and identity.
  return /\b(?:Lark|Feishu)\/[\d.]+/i.test(userAgent);
}

export function suppressAutomaticFeishuLogin() {
  try {
    sessionStorage.setItem(attemptKey, "1");
  } catch {
    // Without persistent tab storage automatic redirects are disabled below.
  }
}

export function claimAutomaticAttempt() {
  try {
    if (sessionStorage.getItem(attemptKey)) return false;
    sessionStorage.setItem(attemptKey, "1");
    return true;
  } catch {
    return false;
  }
}
