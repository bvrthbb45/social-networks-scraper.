import { vi } from "vitest";

/** A route handler returns the JSON body, or `status(code, body)` for a non-200 answer. */
type Route = (url: URL, init: RequestInit) => unknown;
type Tagged = { __status: number; body?: unknown };

export const status = (code: number, body?: unknown): Tagged => ({ __status: code, body });
const isTagged = (v: unknown): v is Tagged => typeof v === "object" && v !== null && "__status" in v;

export interface Recorded {
  key: string; // "METHOD /path" (without the /api prefix)
  body: unknown; // parsed JSON, or the FormData itself
}

/**
 * Replace `fetch` with an in-memory router keyed by "METHOD /path". A request nobody mocked fails
 * the test loudly, so the UI cannot silently call an endpoint the test did not expect.
 */
export function mockApi(routes: Record<string, Route>) {
  const calls: Recorded[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const key = `${init.method ?? "GET"} ${url.pathname.replace(/^\/api/, "")}`;
    const route = routes[key];
    if (!route) throw new Error(`unmocked request: ${key}`);
    calls.push({ key, body: typeof init.body === "string" ? JSON.parse(init.body) : init.body });
    const answer = route(url, init);
    const code = isTagged(answer) ? answer.__status : 200;
    const payload = isTagged(answer) ? answer.body : answer;
    return new Response(code === 204 ? null : JSON.stringify(payload ?? {}), {
      status: code,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return { calls, fn };
}

const ALLOWED_LATIN = ["Google", "Excel", "QR", "Authenticator"];

/** Latin words visible in `text` (product names excepted): there should be none in a Hebrew UI. */
export function latinWords(text: string): string[] {
  const rest = ALLOWED_LATIN.reduce((t, w) => t.replaceAll(w, ""), text);
  return rest.match(/[A-Za-z]{2,}/g) ?? [];
}
