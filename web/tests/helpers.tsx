import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Gate } from "../src/App";
import { AuthProvider } from "../src/auth/AuthContext";
import type { Role } from "../src/api/types";
import { status } from "./mockApi";

export const userFor = (role: Role) => ({
  id: "u1", email: `${role}@example.org`, display_name: "דנה", role, is_active: true, totp_enabled: true, last_login_at: null,
});

/** Routes that make the app believe a user of `role` is already signed in (refresh cookie valid). */
export const signedIn = (role: Role) => ({
  "POST /auth/refresh": () => ({ access_token: "T", token_type: "bearer", expires_in: 600, device_id: "d1" }),
  "GET /auth/me": () => userFor(role),
});

export const signedOut = { "POST /auth/refresh": () => status(401, { detail: "Not authenticated" }) };

export function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider><Gate /></AuthProvider>
    </MemoryRouter>,
  );
}
