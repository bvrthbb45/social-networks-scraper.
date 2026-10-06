// An invitation link is  /?invite=<token>.  The token is a one-time secret: take it out of the
// address bar (history, referrers, screenshots) the moment the app starts, keep it in memory only.
let held: string | null = null;

export function captureInvite(): void {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("invite");
  if (!token) return;
  held = token;
  url.searchParams.delete("invite");
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
}

/** The token captured at startup (or still in the URL), once. */
export function takeInvite(): string | null {
  captureInvite();
  const token = held;
  held = null;
  return token;
}
