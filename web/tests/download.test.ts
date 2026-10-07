import { setAccessToken } from "../src/api/client";
import { androidBridge, downloadFile } from "../src/lib/download";
import { mockApi } from "./mockApi";

afterEach(() => { setAccessToken(null); vi.restoreAllMocks(); delete (window as unknown as { OpsecAndroid?: unknown }).OpsecAndroid; });

describe("downloadFile", () => {
  it("has no bridge in an ordinary browser", () => {
    expect(androidBridge()).toBeNull();
  });

  it("ignores a bridge object that is not callable", () => {
    (window as unknown as { OpsecAndroid?: unknown }).OpsecAndroid = { saveFile: "x" };
    expect(androidBridge()).toBeNull();
  });

  it("hands the bytes to the Android shell instead of clicking a link", async () => {
    const saved: string[][] = [];
    (window as unknown as { OpsecAndroid?: unknown }).OpsecAndroid = { saveFile: (b: string, n: string, m: string) => saved.push([b, n, m]) };
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    mockApi({ "GET /reports/export": () => "x" });
    const api = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === "blob:x" ? ({ blob: async () => new Blob(["hello"], { type: "application/octet-stream" }) } as Response) : api(input, init)));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click");
    await downloadFile("/reports/export", "r.xlsx");
    expect(saved).toEqual([[btoa("hello"), "r.xlsx", "application/octet-stream"]]);
    expect(click).not.toHaveBeenCalled();
  });
});
