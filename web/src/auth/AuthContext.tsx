import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, post, refreshSession, setAccessToken, setSessionLostHandler } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  /** Set when the user was signed out for inactivity (shown on the login screen). */
  idleLogout: boolean;
  startSession: (accessToken: string) => Promise<void>;
  logout: (idle?: boolean) => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [idleLogout, setIdle] = useState(false);

  const loadUser = useCallback(async () => {
    setUser(await api<User>("/auth/me"));
  }, []);

  useEffect(() => {
    setSessionLostHandler(() => setUser(null));
    let alive = true;
    (async () => {
      try {
        if (await refreshSession()) await loadUser();
      } catch { /* not signed in */ }
      if (alive) setLoading(false);
    })();
    return () => { alive = false; setSessionLostHandler(null); };
  }, [loadUser]);

  const startSession = useCallback(async (token: string) => {
    setAccessToken(token);
    setIdle(false);
    await loadUser();
  }, [loadUser]);

  const logout = useCallback(async (idle = false) => {
    try { await post("/auth/logout"); } catch { /* best effort: the device may already be revoked */ }
    setAccessToken(null);
    setIdle(idle);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, loading, idleLogout, startSession, logout }), [user, loading, idleLogout, startSession, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

/** Evidence on screen is sensitive: sign out after a period without any user input. */
export function useIdleLogout(minutes: number, onIdle: () => void) {
  const cb = useRef(onIdle);
  cb.current = onIdle;
  useEffect(() => {
    let timer = window.setTimeout(() => cb.current(), minutes * 60_000);
    const reset = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => cb.current(), minutes * 60_000);
    };
    const events = ["pointerdown", "keydown", "scroll", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }));
    return () => { window.clearTimeout(timer); events.forEach((e) => window.removeEventListener(e, reset)); };
  }, [minutes]);
}
