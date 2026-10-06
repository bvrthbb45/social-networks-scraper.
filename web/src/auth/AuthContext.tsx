import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from "react";
import { api, post, refreshSession, setAccessToken, setSessionLostHandler } from "../api/client";
import type { User } from "../api/types";

type Phase = { status: "restoring" } | { status: "signed-out"; idle: boolean } | { status: "signed-in"; user: User };
type Action =
  | { type: "signed-in"; user: User }
  | { type: "signed-out"; idle?: boolean };

const reduce = (_: Phase, a: Action): Phase =>
  a.type === "signed-in" ? { status: "signed-in", user: a.user } : { status: "signed-out", idle: a.idle ?? false };

interface AuthState {
  user: User | null;
  /** True until the first attempt to resume a session (refresh cookie) has finished. */
  loading: boolean;
  /** The last sign-out happened because the person was inactive. */
  idleLogout: boolean;
  /** Called once password + second factor succeeded and an access token exists. */
  startSession: (accessToken: string) => Promise<void>;
  logout: (idle?: boolean) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [phase, dispatch] = useReducer(reduce, { status: "restoring" } as Phase);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    setSessionLostHandler(() => dispatch({ type: "signed-out" }));
    (async () => {
      let user: User | null = null;
      try {
        if (await refreshSession()) user = await api<User>("/auth/me");
      } catch {
        /* no valid session to resume */
      }
      if (mounted.current) dispatch(user ? { type: "signed-in", user } : { type: "signed-out" });
    })();
    return () => {
      mounted.current = false;
      setSessionLostHandler(null);
    };
  }, []);

  const startSession = useCallback(async (token: string) => {
    setAccessToken(token);
    dispatch({ type: "signed-in", user: await api<User>("/auth/me") });
  }, []);

  const logout = useCallback(async (idle = false) => {
    try {
      await post("/auth/logout");
    } catch {
      /* the device may already be revoked server-side */
    }
    setAccessToken(null);
    dispatch({ type: "signed-out", idle });
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user: phase.status === "signed-in" ? phase.user : null,
      loading: phase.status === "restoring",
      idleLogout: phase.status === "signed-out" && phase.idle,
      startSession,
      logout,
    }),
    [phase, startSession, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Evidence on screen is sensitive: sign the person out after `minutes` without any input. */
export function useIdleLogout(minutes: number, onIdle: () => void): void {
  const callback = useRef(onIdle);
  callback.current = onIdle;

  useEffect(() => {
    const limit = minutes * 60_000;
    let timer = window.setTimeout(() => callback.current(), limit);
    const restart = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => callback.current(), limit);
    };
    const signals = ["pointerdown", "keydown", "scroll", "touchstart"] as const;
    signals.forEach((s) => window.addEventListener(s, restart, { passive: true }));
    return () => {
      window.clearTimeout(timer);
      signals.forEach((s) => window.removeEventListener(s, restart));
    };
  }, [minutes]);
}
