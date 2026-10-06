import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAccessToken } from "../src/api/client";
import { he } from "../src/i18n/he";
import { renderAt, signedIn } from "./helpers";
import { latinWords, mockApi } from "./mockApi";

afterEach(() => { setAccessToken(null); vi.restoreAllMocks(); });
const R = he.reports;

const summary = (o = {}) => ({
  days: 30, findings_created: 42, created_by_kind: { codename: 30, uniform: 12 }, created_by_severity: { high: 10, low: 32 },
  decisions: { confirmed: 5, dismissed: 20, escalated: 2 }, dismissal_reasons: { common_word: 12, not_relevant: 8 },
  false_alarm_by_kind: { codename: { decided: 20, dismissed: 12, rate: 0.6 } }, median_hours_to_decision: 6.5, backlog: 9, oldest_open_hours: 52,
  accounts_by_status: { open: 30, closed: 4 }, imports: { files: 3, rows: 120, rejected_rows: 7 },
  security_events: { "login.failed": 4, "account.locked": 0, "refresh.reuse_detected": 1 }, learning: { version: 2, age_days: 12 }, ...o,
});
const retention = (o = {}) => ({ retention_days: 90, posts_total: 500, overdue: 0, due_within_7_days: 12, oldest_post_days: 88, last_run: { at: "2026-10-06T03:00:00Z", counts: { "purged.posts": 4 } }, ...o });
const consents = () => [
  { consent_id: "c1", soldier: "חייל בדיקה", ref: "F-1", valid_until: "2026-10-12", days_left: 6, accounts: 2 },
  { consent_id: "c2", soldier: "חייל שפג", ref: "F-2", valid_until: "2026-10-01", days_left: -5, accounts: 1 },
];
const routes = (role: "admin" | "auditor", extra: Record<string, () => unknown> = {}) => ({
  ...signedIn(role), "GET /reports/summary": () => summary(), "GET /reports/retention": () => retention(), "GET /reports/consents": () => consents(), ...extra,
});

describe("reports page", () => {
  it("shows aggregates and retention in Hebrew, with nothing identifying", async () => {
    mockApi(routes("auditor"));
    renderAt("/reports");
    expect(await screen.findByText(R.intro)).toBeInTheDocument();
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText(R.hours("6.5"))).toBeInTheDocument();
    expect(screen.getByText(R.events["login.failed"])).toBeInTheDocument();
    expect(screen.queryByText(R.events["account.locked"])).toBeNull(); // zero counts are not listed
    expect(await screen.findByText(R.retention)).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument(); // false-alarm rate for codenames
    expect(latinWords(document.body.textContent ?? "")).toEqual([]);
  });

  it("an auditor never sees (or requests) the consent list that names people", async () => {
    const { calls } = mockApi(routes("auditor"));
    renderAt("/reports");
    await screen.findByText(R.retention);
    expect(screen.queryByText(R.consents)).toBeNull();
    expect(calls.some((c) => c.key === "GET /reports/consents")).toBe(false);
  });

  it("an admin sees who is about to lose their consent, with urgency", async () => {
    mockApi(routes("admin"));
    renderAt("/reports");
    expect(await screen.findByText("חייל בדיקה")).toBeInTheDocument();
    const row = screen.getByText("חייל שפג").closest("tr")!;
    expect(within(row).getByText(R.expired)).toBeInTheDocument();
  });

  it("changing the period re-requests the summary for that window", async () => {
    const urls: string[] = [];
    mockApi(routes("admin", { "GET /reports/summary": () => summary() }));
    const orig = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn((u: RequestInfo | URL, i?: RequestInit) => { urls.push(String(u)); return orig(u, i); }));
    renderAt("/reports");
    await userEvent.selectOptions(await screen.findByLabelText(R.period), "90");
    await waitFor(() => expect(urls.some((u) => u.includes("days=90"))).toBe(true));
  });

  it("flags posts that are overdue for deletion", async () => {
    mockApi(routes("admin", { "GET /reports/retention": () => retention({ overdue: 3, last_run: null }) }));
    renderAt("/reports");
    expect(await screen.findByText(R.neverRun)).toBeInTheDocument();
    const row = screen.getByText(R.overdue).closest("li")!;
    expect(within(row).getByText("3")).toBeInTheDocument();
  });
});

describe("export from the findings queue", () => {
  it("downloads the report through an authenticated request and explains that it is sensitive", async () => {
    const created = vi.fn(() => "blob:report");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() }));
    const { fn } = mockApi({ ...signedIn("reviewer"), "GET /findings": () => [] });
    const base = fn.getMockImplementation()!;
    fn.mockImplementation(async (input: RequestInfo | URL, init: RequestInit = {}) =>
      String(input).includes("/reports/export/") ? new Response("xlsx-bytes", { status: 200 }) : base(input, init));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderAt("/findings");
    expect(await screen.findByText(he.findings.exportNote)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: he.findings.exportConfirmed }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    const call = fn.mock.calls.find(([u]) => String(u).includes("/reports/export/findings"))!;
    expect(String(call[0])).toContain("states=confirmed,escalated");
    expect(((call[1] as RequestInit).headers as Headers).get("Authorization")).toBe("Bearer T");
    expect(created).toHaveBeenCalledOnce();
  });

  it("tells the reviewer when the export fails", async () => {
    const { fn } = mockApi({ ...signedIn("reviewer"), "GET /findings": () => [] });
    const base = fn.getMockImplementation()!;
    fn.mockImplementation(async (input: RequestInfo | URL, init: RequestInit = {}) =>
      String(input).includes("/reports/export/") ? new Response("no", { status: 500 }) : base(input, init));
    renderAt("/findings");
    await userEvent.click(await screen.findByRole("button", { name: he.findings.exportConfirmed }));
    expect(await screen.findByRole("alert")).toHaveTextContent(he.findings.exportFailed);
  });
});
