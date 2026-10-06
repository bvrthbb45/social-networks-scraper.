import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAccessToken } from "../src/api/client";
import { he } from "../src/i18n/he";
import { renderAt, signedIn } from "./helpers";
import { latinWords, mockApi, status } from "./mockApi";

afterEach(() => setAccessToken(null));

const row = (o = {}) => ({
  id: "f1", kind: "codename", severity: "high", score: 0.9, status: "new", reason: "הטקסט מכיל שם קוד מרשימת המעקב",
  source: "text", snippet: "הגענו אל נשר שחור", platform: "instagram", username: "soldier_x", post_url: null, posted_at: null,
  created_at: "2026-10-06T10:00:00Z", ...o,
});
const detail = (o = {}) => ({
  ...row(), engine_version: "rules-1", post_text: "הגענו אל נשר שחור היום", media: [{ index: 0, kind: "image" }], history: [], ...o,
});

describe("findings queue", () => {
  it("lists leads most-suspicious-first with badges, in Hebrew", async () => {
    const { calls } = mockApi({ ...signedIn("reviewer"), "GET /findings": () => [row(), row({ id: "f2", severity: "low", kind: "uniform", score: 0.4 })] });
    const { container } = renderAt("/findings");
    expect(await screen.findAllByRole("link", { name: he.findings.open })).toHaveLength(2);
    expect(screen.getAllByText(he.severity.high).length).toBeGreaterThan(1); // badge (and the filter option)
    expect(screen.getAllByText("@soldier_x", { exact: false })).toHaveLength(2);
    expect(latinWords(container.textContent ?? "").filter((w) => w !== "soldier" && w !== "x")).toEqual([]);
    expect(calls[calls.length - 1].key).toBe("GET /findings");
  });

  it("filters are sent to the server and reset paging", async () => {
    const urls: string[] = [];
    mockApi({ ...signedIn("reviewer"), "GET /findings": (u) => { urls.push(u.search); return []; } });
    renderAt("/findings");
    await screen.findByText(he.findings.empty);
    await userEvent.selectOptions(screen.getByLabelText(he.findings.severity), "high");
    await userEvent.click(screen.getByRole("tab", { name: he.status.dismissed }));
    await waitFor(() => expect(urls.at(-1)).toContain("status_=dismissed"));
    expect(urls.at(-1)).toContain("severity=high");
    expect(urls.at(-1)).toContain("offset=0");
  });
});

describe("finding detail and decision", () => {
  it("keeps images hidden until asked, and only then downloads them", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    const { fn } = mockApi({ ...signedIn("reviewer"), "GET /findings/f1": () => detail() });
    const base = fn.getMockImplementation()!;
    fn.mockImplementation(async (input: RequestInfo | URL, init: RequestInit = {}) =>
      String(input).includes("/media/") ? new Response("x", { status: 200 }) : base(input, init));
    renderAt("/findings/f1");
    expect(await screen.findByText(he.findings.imageHidden)).toBeInTheDocument();
    expect(fn.mock.calls.some(([u]) => String(u).includes("/media/"))).toBe(false); // nothing fetched yet
    expect(screen.queryByRole("img")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: he.findings.showImage }));
    await waitFor(() => expect(fn.mock.calls.some(([u]) => String(u).includes("/media/"))).toBe(true));
    expect(await screen.findByRole("img")).toHaveAttribute("src", "blob:x");
    await userEvent.click(screen.getByRole("button", { name: he.findings.hideImage }));
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("dismissal sends a structured reason and the note; confirm sends no reason", async () => {
    const { calls } = mockApi({ ...signedIn("reviewer"), "GET /findings/f1": () => detail({ media: [] }), "POST /findings/f1/decision": () => ({ id: "f1", status: "dismissed" }) });
    renderAt("/findings/f1");
    await userEvent.click(await screen.findByRole("button", { name: he.findings.dismiss }));
    await userEvent.selectOptions(screen.getByLabelText(he.findings.reasonLabel), "common_word");
    await userEvent.type(screen.getByLabelText(he.findings.noteLabel), "מילה רגילה");
    await userEvent.click(screen.getByRole("button", { name: he.common.save }));
    await waitFor(() => expect(calls.find((c) => c.key === "POST /findings/f1/decision")?.body).toEqual({ decision: "dismissed", reason: "common_word", note: "מילה רגילה" }));
    expect(await screen.findByText(he.findings.saved, { exact: false })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: he.findings.confirm }));
    await userEvent.click(screen.getByRole("button", { name: he.common.save }));
    await waitFor(() => expect(calls.filter((c) => c.key === "POST /findings/f1/decision")[1].body).toEqual({ decision: "confirmed" }));
  });

  it("shows prior decisions and a Hebrew error when saving is refused", async () => {
    mockApi({
      ...signedIn("reviewer"),
      "GET /findings/f1": () => detail({ media: [], history: [{ decision: "dismissed", reason: "common_word", note: "הערה", reviewer: "דנה", decided_at: "2026-10-06T11:00:00Z" }] }),
      "POST /findings/f1/decision": () => status(403, { detail: "Insufficient role" }),
    });
    renderAt("/findings/f1");
    expect(await screen.findByText("הערה")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: he.findings.escalate }));
    await userEvent.click(screen.getByRole("button", { name: he.common.save }));
    expect(await screen.findByRole("alert")).toHaveTextContent(he.common.forbidden);
  });

  it("states plainly that a person decides and flags weak colour hits", async () => {
    mockApi({ ...signedIn("reviewer"), "GET /findings/f1": () => detail({ kind: "uniform", severity: "low", score: 0.45, media: [], snippet: null }) });
    renderAt("/findings/f1");
    expect(await screen.findByText(he.findings.humanOnly)).toBeInTheDocument();
    expect(screen.getByText(he.findings.lowConfidence)).toBeInTheDocument();
  });
});
