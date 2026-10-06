import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAccessToken } from "../src/api/client";
import type { Role } from "../src/api/types";
import { he } from "../src/i18n/he";
import { navFor } from "../src/lib/roles";
import { renderAt, signedIn, userFor } from "./helpers";
import { latinWords, mockApi, status } from "./mockApi";

afterEach(() => setAccessToken(null));

const stats = { findings_by_status: { new: 3, dismissed: 2 }, open_by_severity: { high: 1, low: 2 }, open_by_kind: { codename: 2, uniform: 1 }, accounts_by_status: { open: 4, closed: 1 }, last_import_at: null };

describe("navigation follows the role", () => {
  const cases: [Role, string[]][] = [
    ["reviewer", [he.nav.dashboard, he.nav.findings, he.nav.people, he.nav.account]],
    ["uploader", [he.nav.imports, he.nav.account]],
    ["auditor", [he.nav.dashboard, he.nav.imports, he.nav.audit, he.nav.account]],
    ["admin", [he.nav.dashboard, he.nav.findings, he.nav.people, he.nav.imports, he.nav.watchlist, he.nav.learning, he.nav.users, he.nav.audit, he.nav.account]],
  ];
  it.each(cases)("%s sees exactly its own sections", async (role, labels) => {
    mockApi({ ...signedIn(role), "GET /stats": () => stats, "GET /imports": () => [], "GET /auth/devices": () => [], "GET /audit": () => [] });
    renderAt(navFor(role)[0].to);
    const nav = (await screen.findAllByRole("navigation", { name: he.nav.main }))[0];
    const shown = within(nav).getAllByRole("link").map((a) => a.textContent!.replace(/^\S\s?/, "").trim());
    expect(shown.map((s) => s.replace(/[^֐-׿\s]/g, "").trim())).toEqual(labels);
  });

  it.each<[Role, string]>([["uploader", "/users"], ["reviewer", "/watchlist"], ["auditor", "/findings"], ["reviewer", "/audit"]])(
    "%s is redirected away from %s",
    async (role, path) => {
      const { calls } = mockApi({ ...signedIn(role), "GET /stats": () => stats, "GET /imports": () => [], "GET /auth/devices": () => [] });
      renderAt(path);
      await screen.findAllByRole("navigation", { name: he.nav.main });
      expect(calls.some((c) => c.key === "GET /users" || c.key === "GET /watchlist" || c.key === "GET /audit")).toBe(false);
    },
  );
});

describe("dashboard", () => {
  it("shows aggregates in Hebrew with no Latin text", async () => {
    mockApi({ ...signedIn("reviewer"), "GET /stats": () => stats });
    const { container } = renderAt("/");
    expect(await screen.findByText(he.dashboard.openFindings)).toBeInTheDocument();
    expect(screen.getByText(he.kind.codename)).toBeInTheDocument();
    expect(latinWords(container.textContent ?? "")).toEqual([]);
  });
});

describe("people", () => {
  const row = { id: "s1", full_name: "חייל בדוי", unit: "יחידה א", accounts: 2, consents: [{ id: "c1", ref: "FORM-1", status: "active", valid_until: "2027-01-01" }] };

  it("admin can revoke a consent only after confirming", async () => {
    const { calls } = mockApi({ ...signedIn("admin"), "GET /soldiers": () => [row], "POST /consents/c1/revoke": () => ({ status: "revoked", accounts_deleted: 2 }) });
    renderAt("/people");
    await userEvent.click(await screen.findByRole("button", { name: he.people.revoke }));
    expect(calls.some((c) => c.key.startsWith("POST /consents"))).toBe(false); // nothing yet
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(he.people.revokeWarn);
    await userEvent.click(within(dialog).getByRole("button", { name: he.people.revoke }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /consents/c1/revoke")).toBe(true));
    expect(await screen.findByText(he.people.revoked)).toBeInTheDocument();
  });

  it("cancelling the confirmation does nothing", async () => {
    const { calls } = mockApi({ ...signedIn("admin"), "GET /soldiers": () => [row] });
    renderAt("/people");
    await userEvent.click(await screen.findByRole("button", { name: he.people.erase }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: he.common.cancel }));
    expect(calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a reviewer can read but sees no destructive actions", async () => {
    mockApi({ ...signedIn("reviewer"), "GET /soldiers": () => [row] });
    renderAt("/people");
    expect(await screen.findByText("חייל בדוי")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: he.people.revoke })).toBeNull();
    expect(screen.queryByRole("button", { name: he.people.erase })).toBeNull();
  });
});

describe("users (admin)", () => {
  const invite = { user_id: "n1", token: "TOKEN-ABC", expires_at: "2026-10-09T00:00:00Z", purpose: "invite" };

  it("creating a user shows a one-time invitation link", async () => {
    const { calls } = mockApi({ ...signedIn("admin"), "GET /users": () => [userFor("admin")], "POST /users": () => invite });
    renderAt("/users");
    await userEvent.click(await screen.findByRole("button", { name: he.users.create }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(he.users.email), "new@example.org");
    await userEvent.click(within(dialog).getByRole("button", { name: he.users.create }));
    expect(await screen.findByTestId("invite-link")).toHaveTextContent("?invite=TOKEN-ABC");
    expect(calls.find((c) => c.key === "POST /users")!.body).toMatchObject({ email: "new@example.org", role: "reviewer" });
  });

  it("explains refusals (last admin / self) in Hebrew", async () => {
    mockApi({ ...signedIn("admin"), "GET /users": () => [userFor("admin"), { ...userFor("reviewer"), id: "u2" }], "PATCH /users/u2": () => status(409, { detail: "Cannot remove the last administrator" }) });
    renderAt("/users");
    await userEvent.click((await screen.findAllByRole("button", { name: he.users.deactivate }))[1]);
    expect(await screen.findByRole("alert")).toHaveTextContent(he.users.conflict);
  });

  it("an admin cannot change or disable their own account from the UI", async () => {
    mockApi({ ...signedIn("admin"), "GET /users": () => [userFor("admin")] });
    renderAt("/users");
    expect(await screen.findByRole("button", { name: he.users.deactivate })).toBeDisabled();
    expect(screen.getByLabelText(new RegExp(`${he.users.role}: admin@example.org`))).toBeDisabled();
  });
});

describe("unused", () => { it("status helper exists", () => { expect(status(1).__status).toBe(1); }); });
