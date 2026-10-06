import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAccessToken } from "../src/api/client";
import { he } from "../src/i18n/he";
import { renderAt, signedIn } from "./helpers";
import { latinWords, mockApi, status } from "./mockApi";

afterEach(() => setAccessToken(null));
const L = he.learning;

const model = (o = {}) => ({
  id: "m1", version: 1, status: "candidate", trained_on: 60, note: null, approvals: 1, created_at: "2026-10-06T10:00:00Z", activated_at: null,
  metrics: { baseline_auc: 0.5, model_auc: 0.93, n_labels: 60, blockers: [] }, ...o,
});
const st = (o = {}) => ({ labels: 60, positives: 30, min_labels: 40, required_approvals: 2, golden_cases: 4, active: null, undecided_open: 3, ...o });
const base = (extra: Record<string, () => unknown> = {}) => ({
  ...signedIn("admin"),
  "GET /learning/status": () => st(), "GET /learning/models": () => [model()], "GET /learning/terms": () => [],
  "GET /learning/term-suggestions": () => [], "GET /learning/golden": () => [], ...extra,
});

describe("learning page", () => {
  it("shows the state in Hebrew and says plainly that nothing is decided automatically", async () => {
    mockApi(base());
    renderAt("/learning");
    expect(await screen.findByText(L.intro)).toBeInTheDocument();
    expect(screen.getByText(L.noActive)).toBeInTheDocument();
    expect(screen.getByText("93%")).toBeInTheDocument(); // model vs engine accuracy side by side
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(latinWords(document.body.textContent ?? "")).toEqual([]);
  });

  it("trains a candidate and reports insufficient data in Hebrew", async () => {
    const { calls } = mockApi(base({ "POST /learning/train": () => status(422, { detail: "insufficient_labels" }) }));
    renderAt("/learning");
    await userEvent.click(await screen.findByRole("button", { name: L.train }));
    expect(await screen.findByRole("alert")).toHaveTextContent(L.errors.insufficient_labels);
    expect(calls.some((c) => c.key === "POST /learning/train")).toBe(true);
  });

  it.each([
    ["needs_more_approvals", L.errors.needs_more_approvals],
    ["golden_failed", L.errors.golden_failed],
    ["not_better_than_baseline", L.errors.not_better_than_baseline],
  ])("activation refusal %s is explained", async (code, text) => {
    mockApi(base({ "POST /learning/models/m1/activate": () => status(409, { detail: code }) }));
    renderAt("/learning");
    await userEvent.click(await screen.findByRole("button", { name: L.activate }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("shows blockers on a model that must not be activated", async () => {
    mockApi(base({ "GET /learning/models": () => [model({ metrics: { baseline_auc: 0.6, model_auc: 0.55, n_labels: 60, blockers: ["not_better_than_baseline", "golden_failed"] } })] }));
    renderAt("/learning");
    expect(await screen.findByText(L.errors.golden_failed)).toBeInTheDocument();
    expect(screen.getByText(L.errors.not_better_than_baseline)).toBeInTheDocument();
  });

  it("approve and shadow call the right endpoints; the approval count is visible", async () => {
    const { calls } = mockApi(base({ "POST /learning/models/m1/approve": () => model({ approvals: 2 }), "POST /learning/models/m1/shadow": () => model({ status: "shadow" }) }));
    renderAt("/learning");
    expect(await screen.findByText("1/2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: L.approve }));
    await userEvent.click(screen.getByRole("button", { name: L.shadow }));
    await waitFor(() => expect(calls.map((c) => c.key)).toEqual(expect.arrayContaining(["POST /learning/models/m1/approve", "POST /learning/models/m1/shadow"])));
  });

  it("rolling back needs an explicit confirmation", async () => {
    const active = model({ status: "active", approvals: 2 });
    const { calls } = mockApi(base({ "GET /learning/status": () => st({ active }), "GET /learning/models": () => [active], "POST /learning/rollback": () => ({ to: "baseline" }) }));
    renderAt("/learning");
    await userEvent.click(await screen.findByRole("button", { name: L.rollback }));
    expect(calls.some((c) => c.key === "POST /learning/rollback")).toBe(false);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(L.rollbackWarn);
    await userEvent.click(within(dialog).getByRole("button", { name: L.rollback }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /learning/rollback")).toBe(true));
    expect(await screen.findByText(L.rolledBack)).toBeInTheDocument();
  });

  it("flags noisy terms and offers suggestions as counts only, added only on request", async () => {
    const { calls } = mockApi(base({
      "GET /learning/terms": () => [{ id: "t1", term: "נשר", severity: "medium", n: 8, confirmed: 1, precision: 0.125, advice: "mostly_false_alarms", dismiss_reasons: { common_word: 7 } }],
      "GET /learning/term-suggestions": () => [{ token: "שקנאי", confirmed_posts: 3, accounts: 2, dismissed_posts: 0 }],
      "POST /watchlist": () => ({ id: "t2" }),
    }));
    renderAt("/learning");
    expect(await screen.findByText(L.advice.mostly_false_alarms)).toBeInTheDocument();
    expect(screen.getByText("שקנאי")).toBeInTheDocument();
    expect(calls.some((c) => c.key === "POST /watchlist")).toBe(false); // a suggestion is never applied by itself
    await userEvent.click(screen.getByRole("button", { name: L.addTerm }));
    await waitFor(() => expect(calls.find((c) => c.key === "POST /watchlist")?.body).toEqual({ term: "שקנאי", kind: "codename", severity: "medium" }));
    expect(await screen.findByText(L.added)).toBeInTheDocument();
  });

  it("manages golden cases", async () => {
    const { calls } = mockApi(base({ "POST /learning/golden": () => ({ id: "g1" }) }));
    renderAt("/learning");
    await userEvent.type(await screen.findByLabelText(L.goldenText), "משפט שחייבים לתפוס");
    await userEvent.click(screen.getByRole("button", { name: L.addGolden }));
    await waitFor(() => expect(calls.find((c) => c.key === "POST /learning/golden")?.body).toEqual({ text: "משפט שחייבים לתפוס", kind: "codename" }));
  });

  it.each(["reviewer", "uploader", "auditor"] as const)("%s cannot reach the page and never calls the API", async (role) => {
    const { calls } = mockApi({ ...signedIn(role), "GET /stats": () => ({ findings_by_status: {}, open_by_severity: {}, open_by_kind: {}, accounts_by_status: {}, last_import_at: null }), "GET /imports": () => [], "GET /auth/devices": () => [] });
    renderAt("/learning");
    await screen.findAllByRole("navigation");
    expect(calls.some((c) => c.key.startsWith("GET /learning"))).toBe(false);
  });
});

describe("queue and detail with a learned model", () => {
  const row = (o = {}) => ({ id: "f1", kind: "codename", severity: "medium", score: 0.55, adjusted_score: 0.2, lane: "low", status: "new", reason: "סיבה", source: "text", snippet: "x", platform: "instagram", username: "u", post_url: null, posted_at: null, created_at: "2026-10-06T10:00:00Z", ...o });

  it("marks the low-priority lane, shows the learned score and sends the chosen order", async () => {
    const urls: string[] = [];
    mockApi({ ...signedIn("reviewer"), "GET /findings": (u) => { urls.push(u.search); return [row(), row({ id: "f2", adjusted_score: null, lane: "normal", score: 0.9 })]; } });
    renderAt("/findings");
    expect(await screen.findByText(he.findings.lowLane)).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument(); // learned score is what is shown and ranked
    expect(screen.getByText("90%")).toBeInTheDocument(); // no model opinion: the engine score
    await userEvent.selectOptions(screen.getByLabelText(he.findings.order), "uncertain");
    await waitFor(() => expect(urls.at(-1)).toContain("order=uncertain"));
  });

  it("explains the learned score in the detail page and keeps the engine score visible", async () => {
    mockApi({ ...signedIn("reviewer"), "GET /findings/f1": () => ({ ...row(), learning: ["על מונח זה התקבלו 60 החלטות, 30 מהן אושרו"], engine_version: "rules-1", post_text: "טקסט", media: [], history: [] }) });
    renderAt("/findings/f1");
    expect(await screen.findByText(he.findings.learningTitle)).toBeInTheDocument();
    expect(screen.getByText("על מונח זה התקבלו 60 החלטות, 30 מהן אושרו")).toBeInTheDocument();
    expect(screen.getByText(he.findings.learningNote)).toBeInTheDocument();
    expect(screen.getByText(/55%/)).toBeInTheDocument();
  });
});
