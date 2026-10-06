import { ApiError, api, blobUrl, refreshSession, setAccessToken, setSessionLostHandler, upload } from "../src/api/client";
import { mockApi, status } from "./mockApi";

const FRESH = { access_token: "FRESH", token_type: "bearer", expires_in: 600, device_id: "d" };
const bearerOf = (init: unknown) => ((init as RequestInit).headers as Headers).get("Authorization");

afterEach(() => {
  setAccessToken(null);
  setSessionLostHandler(null);
});

describe("silent session refresh", () => {
  it("retries a 401 once with the refreshed token", async () => {
    setAccessToken("STALE");
    let answered = false;
    const { fn } = mockApi({
      "GET /items": () => (answered ? { ok: true } : ((answered = true), status(401, {}))),
      "POST /auth/refresh": () => FRESH,
    });
    expect(await api("/items")).toEqual({ ok: true });
    const attempts = fn.mock.calls.filter(([u]) => String(u).endsWith("/items"));
    expect(attempts).toHaveLength(2);
    expect(bearerOf(attempts[0][1])).toBe("Bearer STALE");
    expect(bearerOf(attempts[1][1])).toBe("Bearer FRESH");
  });

  it("tells the app the session is gone when the refresh is refused", async () => {
    setAccessToken("STALE");
    const lost = vi.fn();
    setSessionLostHandler(lost);
    mockApi({ "GET /items": () => status(401, {}), "POST /auth/refresh": () => status(401, {}) });
    await expect(api("/items")).rejects.toMatchObject({ status: 401 });
    expect(lost).toHaveBeenCalledTimes(1);
  });

  it("makes parallel requests share a single refresh", async () => {
    setAccessToken("STALE");
    const fresh = (_u: URL, init: RequestInit) => (bearerOf(init) === "Bearer FRESH" ? { ok: 1 } : status(401, {}));
    const { calls } = mockApi({ "GET /a": fresh, "GET /b": fresh, "POST /auth/refresh": () => FRESH });
    await Promise.all([api("/a"), api("/b")]);
    expect(calls.filter((c) => c.key === "POST /auth/refresh")).toHaveLength(1);
  });

  it("never refreshes on behalf of a sign-in step token", async () => {
    const { calls } = mockApi({ "POST /auth/2fa/verify": () => status(401, { detail: "Invalid code" }) });
    await expect(api("/auth/2fa/verify", { method: "POST", body: {}, token: "STEP" })).rejects.toBeInstanceOf(ApiError);
    expect(calls.map((c) => c.key)).not.toContain("POST /auth/refresh");
  });

  it("reports whether refreshing worked", async () => {
    mockApi({ "POST /auth/refresh": () => FRESH });
    expect(await refreshSession()).toBe(true);
    mockApi({ "POST /auth/refresh": () => status(401, {}) });
    expect(await refreshSession()).toBe(false);
  });
});

describe("requests", () => {
  it("turns a network failure into ApiError status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(api("/x", { anonymous: true })).rejects.toMatchObject({ status: 0 });
  });

  it("surfaces the server's error text", async () => {
    mockApi({ "GET /x": () => status(409, { detail: "Cannot remove the last administrator" }) });
    await expect(api("/x", { anonymous: true })).rejects.toMatchObject({ status: 409, detail: "Cannot remove the last administrator" });
  });

  it("sends JSON bodies as JSON and files as multipart (no hand-set Content-Type)", async () => {
    const { fn } = mockApi({ "POST /j": () => ({}), "POST /f": () => ({}) });
    await api("/j", { method: "POST", body: { a: 1 }, anonymous: true });
    const form = new FormData();
    form.append("file", new File(["x"], "r.xlsx"));
    await upload("/f", form);
    const headersOf = (path: string) => (fn.mock.calls.find(([u]) => String(u).endsWith(path))![1] as RequestInit).headers as Headers;
    expect(headersOf("/j").get("Content-Type")).toBe("application/json");
    expect(headersOf("/f").get("Content-Type")).toBeNull();
  });

  it("downloads binary content as an object URL", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:ok") }));
    vi.stubGlobal("fetch", vi.fn(async () => new Response("bytes", { status: 200 })));
    expect(await blobUrl("/media/1")).toBe("blob:ok");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("no", { status: 404 })));
    await expect(blobUrl("/media/2")).rejects.toMatchObject({ status: 404 });
  });

  it("keeps tokens out of web storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const getItem = vi.spyOn(Storage.prototype, "getItem");
    setAccessToken("SECRET");
    mockApi({ "GET /x": () => ({ ok: true }) });
    await api("/x");
    expect(setItem).not.toHaveBeenCalled();
    expect(getItem).not.toHaveBeenCalled();
  });
});
