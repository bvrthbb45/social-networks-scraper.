import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { Gate } from "../src/App";
import { AuthProvider } from "../src/auth/AuthContext";
import { setAccessToken } from "../src/api/client";
import { IDLE_MINUTES } from "../src/components/Layout";
import { he } from "../src/i18n/he";
import { signedIn, signedOut } from "./helpers";
import { mockApi } from "./mockApi";

afterEach(() => { setAccessToken(null); vi.useRealTimers(); window.history.replaceState(null, "", "/"); });

describe("idle sign-out", () => {
  it("signs out after the idle period and says why", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { calls } = mockApi({ ...signedIn("reviewer"), "GET /stats": () => ({ findings_by_status: {}, open_by_severity: {}, open_by_kind: {}, accounts_by_status: {}, last_import_at: null }), "POST /auth/logout": () => ({}) });
    render(<MemoryRouter><AuthProvider><Gate /></AuthProvider></MemoryRouter>);
    await screen.findAllByRole("navigation");
    await act(async () => { await vi.advanceTimersByTimeAsync((IDLE_MINUTES - 1) * 60_000); });
    expect(calls.some((c) => c.key === "POST /auth/logout")).toBe(false);
    window.dispatchEvent(new Event("pointerdown")); // activity resets the clock
    await act(async () => { await vi.advanceTimersByTimeAsync((IDLE_MINUTES - 1) * 60_000); });
    expect(calls.some((c) => c.key === "POST /auth/logout")).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(2 * 60_000); });
    await waitFor(() => expect(calls.some((c) => c.key === "POST /auth/logout")).toBe(true));
    expect(await screen.findByText(he.auth.idleLogout)).toBeInTheDocument();
  });
});

describe("invitation link", () => {
  it("takes the token out of the address bar, sets the password, then enrols 2FA", async () => {
    window.history.replaceState(null, "", "/?invite=SECRET-TOKEN-VALUE-1234567890");
    const { calls } = mockApi({
      ...signedOut,
      "POST /auth/accept-invite": () => ({ status: "2fa_setup_required", token: "SETUP" }),
      "POST /auth/2fa/setup": () => ({ secret: "ABCDEFGH", otpauth_uri: "otpauth://totp/x?secret=ABCDEFGH" }),
    });
    render(<MemoryRouter><AuthProvider><Gate /></AuthProvider></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: he.auth.inviteTitle })).toBeInTheDocument();
    expect(window.location.search).toBe(""); // the secret does not linger in history / referrers
    await userEvent.type(screen.getByLabelText(he.auth.password), "correct horse battery 7");
    await userEvent.click(screen.getByRole("button", { name: he.auth.setPassword }));
    expect(await screen.findByRole("heading", { name: he.auth.setupTitle })).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /auth/accept-invite")!.body).toEqual({ token: "SECRET-TOKEN-VALUE-1234567890", password: "correct horse battery 7" });
  });

  it("shows a clear message for an expired invitation", async () => {
    window.history.replaceState(null, "", "/?invite=EXPIRED-EXPIRED-EXPIRED-1");
    mockApi({ ...signedOut, "POST /auth/accept-invite": () => ({ __status: 400, body: { detail: "Invalid or expired invitation" } }) });
    render(<MemoryRouter><AuthProvider><Gate /></AuthProvider></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText(he.auth.password), "correct horse battery 7");
    await userEvent.click(screen.getByRole("button", { name: he.auth.setPassword }));
    expect(await screen.findByRole("alert")).toHaveTextContent(he.auth.inviteInvalid);
  });
});

describe("login", () => {
  it("sends the client kind so the server creates a web device", async () => {
    const { calls } = mockApi({ ...signedOut, "POST /auth/login": () => ({ status: "mfa_required", token: "STEP" }) });
    render(<MemoryRouter><AuthProvider><Gate /></AuthProvider></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText(he.auth.email), "a@example.org");
    await userEvent.type(screen.getByLabelText(he.auth.password), "whatever-pass-1");
    await userEvent.click(screen.getByRole("button", { name: he.auth.login }));
    await screen.findByRole("heading", { name: he.auth.mfaTitle });
    expect(calls.find((c) => c.key === "POST /auth/login")!.body).toMatchObject({ email: "a@example.org", client: "web" });
  });

  it("registers an android device when running inside the Android shell", async () => {
    (window as unknown as { OpsecAndroid?: unknown }).OpsecAndroid = { saveFile: () => {} };
    try {
      const { calls } = mockApi({ ...signedOut, "POST /auth/login": () => ({ status: "mfa_required", token: "STEP" }) });
      render(<MemoryRouter><AuthProvider><Gate /></AuthProvider></MemoryRouter>);
      await userEvent.type(await screen.findByLabelText(he.auth.email), "a@example.org");
      await userEvent.type(screen.getByLabelText(he.auth.password), "whatever-pass-1");
      await userEvent.click(screen.getByRole("button", { name: he.auth.login }));
      await screen.findByRole("heading", { name: he.auth.mfaTitle });
      expect(calls.find((c) => c.key === "POST /auth/login")!.body).toMatchObject({ client: "android", device_name: he.auth.androidDevice });
    } finally {
      delete (window as unknown as { OpsecAndroid?: unknown }).OpsecAndroid;
    }
  });
});
