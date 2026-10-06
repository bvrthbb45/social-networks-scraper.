import { ApiError, api, setAccessToken, setSessionLostHandler } from "../src/api/client";
import { mockApi, status } from "./mockApi";

afterEach(() => { setAccessToken(null); setSessionLostHandler(null); });

describe("api client", () => {
  it("silently refreshes once on 401 and retries with the new token", async () => {
    setAccessToken("OLD");
    let first = true;
    const { fn } = mockApi({
      "GET /thing": () => { if (first) { first = false; return status(401, { detail: "x" }); } return { ok: true }; },
      "POST /auth/refresh": () => ({ access_token: "NEW", token_type: "bearer", expires_in: 900, recovery_codes: null }),
    });
    expect(await api("/thing")).toEqual({ ok: true });
    const retry = fn.mock.calls.filter(([u]) => String(u).endsWith("/thing"))[1][1] as RequestInit;
    expect(retry.headers).toMatchObject({ Authorization: "Bearer NEW" });
  });

  it("signs the user out when refresh fails", async () => {
    setAccessToken("OLD");
    const lost = vi.fn();
    setSessionLostHandler(lost);
    mockApi({ "GET /thing": () => status(401, {}), "POST /auth/refresh": () => status(401, {}) });
    await expect(api("/thing")).rejects.toMatchObject({ status: 401 });
    expect(lost).toHaveBeenCalledOnce();
  });

  it("shares one refresh between concurrent requests", async () => {
    setAccessToken("OLD");
    const { calls } = mockApi({
      "GET /a": (_u, init) => ((init.headers as Record<string, string>).Authorization === "Bearer NEW" ? { a: 1 } : status(401, {})),
      "GET /b": (_u, init) => ((init.headers as Record<string, string>).Authorization === "Bearer NEW" ? { b: 1 } : status(401, {})),
      "POST /auth/refresh": () => ({ access_token: "NEW", token_type: "bearer", expires_in: 900, recovery_codes: null }),
    });
    await Promise.all([api("/a"), api("/b")]);
    expect(calls.filter((c) => c.key === "POST /auth/refresh")).toHaveLength(1);
  });

  it("never refreshes for explicit step tokens and surfaces the API error", async () => {
    const { calls } = mockApi({ "POST /auth/2fa/verify": () => status(401, { detail: "Invalid code" }) });
    await expect(api("/auth/2fa/verify", { method: "POST", body: {}, token: "STEP" })).rejects.toBeInstanceOf(ApiError);
    expect(calls.some((c) => c.key === "POST /auth/refresh")).toBe(false);
  });

  it("maps network failures to status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    await expect(api("/x", { noAuth: true })).rejects.toMatchObject({ status: 0 });
  });

  it("never reads tokens from or writes tokens to web storage", async () => {
    setAccessToken("SECRET");
    mockApi({ "GET /x": () => ({}) });
    await api("/x");
    expect(JSON.stringify({ ...localStorage })).not.toContain("SECRET");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("SECRET");
  });
});
