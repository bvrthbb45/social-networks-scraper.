// HTTP client for the monitor API.
//
// Session model: the short-lived access token is kept in a module variable only (never in web
// storage, so a script injected into the page cannot read it from there). The long-lived refresh
// credential is an httpOnly cookie the browser sends by itself; a 401 triggers one silent refresh.

import type { Session } from "./types";

const API_ROOT: string = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Bearer for the sign-in steps (password-ok / 2FA-setup tokens); disables auto-refresh. */
  token?: string;
  /** Send without any Authorization header. */
  anonymous?: boolean;
}

let accessToken: string | null = null;
let whenSessionLost: (() => void) | undefined;
let refreshInFlight: Promise<boolean> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}
export function setSessionLostHandler(handler: (() => void) | null): void {
  whenSessionLost = handler ?? undefined;
}

function buildInit(opts: RequestOptions): RequestInit {
  const headers = new Headers();
  const bearer = opts.token ?? (opts.anonymous ? null : accessToken);
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);

  const init: RequestInit = { method: opts.method ?? "GET", headers, credentials: "include" };
  if (opts.body instanceof FormData) {
    init.body = opts.body; // the browser sets the multipart boundary itself
  } else if (opts.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(opts.body);
  }
  return init;
}

async function transport(path: string, opts: RequestOptions): Promise<Response> {
  try {
    return await fetch(`${API_ROOT}${path}`, buildInit(opts));
  } catch {
    throw new ApiError(0, "network");
  }
}

/** Ask the server for a fresh access token using the refresh cookie. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await transport("/auth/refresh", { method: "POST", anonymous: true });
        if (!res.ok) return false;
        accessToken = ((await res.json()) as Session).access_token;
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

async function sendWithRefresh(path: string, opts: RequestOptions): Promise<Response> {
  const res = await transport(path, opts);
  const refreshable = res.status === 401 && !opts.token && !opts.anonymous;
  if (!refreshable) return res;
  if (await refreshSession()) return transport(path, opts);
  accessToken = null;
  whenSessionLost?.();
  return res;
}

async function failure(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const payload = await res.json();
    detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
  } catch {
    /* the error body was not JSON */
  }
  return new ApiError(res.status, detail);
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await sendWithRefresh(path, opts);
  if (!res.ok) throw await failure(res);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, body?: unknown, opts: RequestOptions = {}) =>
  api<T>(path, { ...opts, method: "POST", body });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });
export const del = (path: string) => api<void>(path, { method: "DELETE" });
export const upload = <T,>(path: string, form: FormData) => api<T>(path, { method: "POST", body: form });

/** Download authenticated binary content (evidence images) as a temporary object URL. */
export async function blobUrl(path: string): Promise<string> {
  const res = await sendWithRefresh(path, {});
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return URL.createObjectURL(await res.blob());
}
