import { vi } from "vitest";

type Handler = (url: URL, init: RequestInit) => unknown | { __status: number; body?: unknown };
export const status = (code: number, body?: unknown) => ({ __status: code, body });

/** Replace fetch with a tiny router keyed by "METHOD /path". Unknown routes fail the test. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; body: unknown }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    const key = `${init.method ?? "GET"} ${path}`;
    const handler = routes[key];
    if (!handler) throw new Error(`unmocked request: ${key}`);
    calls.push({ key, body: typeof init.body === "string" ? JSON.parse(init.body) : init.body });
    const out = handler(url, init) as { __status?: number; body?: unknown } | undefined;
    const code = out && typeof out === "object" && "__status" in out ? out.__status! : 200;
    const body = out && typeof out === "object" && "__status" in out ? out.body : out;
    return new Response(code === 204 ? null : JSON.stringify(body ?? {}), {
      status: code,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return { calls, fn };
}

export const ALLOWED_LATIN = ["Google", "Excel", "QR", "Authenticator"];

/** Visible text must be Hebrew (brand names excepted); returns offending words. */
export function latinWords(text: string): string[] {
  let rest = text;
  for (const w of ALLOWED_LATIN) rest = rest.replaceAll(w, "");
  return rest.match(/[A-Za-z]{2,}/g) ?? [];
}
