import type { Session } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

// The access token lives only in memory (never localStorage): an XSS cannot
// read it from storage, and the httpOnly refresh cookie restores sessions.
let accessToken: string | null = null;
let onSessionLost: (() => void) | null = null;
let refreshing: Promise<boolean> | null = null;

export const setAccessToken = (t: string | null) => { accessToken = t; };
export const setSessionLostHandler = (fn: (() => void) | null) => { onSessionLost = fn; };

interface Options {
  method?: string;
  body?: unknown;
  token?: string;      // explicit bearer (login step tokens)
  noAuth?: boolean;
  noRefresh?: boolean;
}

async function send(path: string, opts: Options): Promise<Response> {
  const headers: Record<string, string> = {};
  const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
  if (opts.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const token = opts.token ?? (opts.noAuth ? null : accessToken);
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    return await fetch(`${BASE}${path}`, {
      method: opts.method ?? "GET",
      headers,
      credentials: "include",
      body: opts.body === undefined ? undefined : isForm ? (opts.body as FormData) : JSON.stringify(opts.body),
    });
  } catch {
    throw new ApiError(0, "network");
  }
}

export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await send("/auth/refresh", { method: "POST", noAuth: true, noRefresh: true });
      if (!res.ok) return false;
      accessToken = ((await res.json()) as Session).access_token;
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  let res = await send(path, opts);
  if (res.status === 401 && !opts.token && !opts.noAuth && !opts.noRefresh) {
    if (await refreshSession()) res = await send(path, opts);
    else { accessToken = null; onSessionLost?.(); }
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, body?: unknown, opts: Options = {}) =>
  api<T>(path, { ...opts, method: "POST", body });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });
export const del = (path: string) => api<void>(path, { method: "DELETE" });

/** Authenticated binary download (evidence images). Returned as a short-lived object URL. */
export async function blobUrl(path: string): Promise<string> {
  let res = await send(path, {});
  if (res.status === 401 && (await refreshSession())) res = await send(path, {});
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return URL.createObjectURL(await res.blob());
}

export const upload = <T,>(path: string, form: FormData) => api<T>(path, { method: "POST", body: form });
