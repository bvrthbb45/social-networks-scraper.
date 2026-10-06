import { useEffect, useState, type FormEvent } from "react";
import QRCode from "qrcode";
import { ApiError, post } from "../api/client";
import type { Session, StepToken, TotpSetup } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorBox, Field, Notice } from "../components/ui";
import { he } from "../i18n/he";
import { takeInvite } from "../lib/invite";
import { errorMessage } from "../lib/useAsync";

type Step =
  | { kind: "credentials" }
  | { kind: "invite"; token: string }
  | { kind: "mfa"; token: string }
  | { kind: "setup"; token: string }
  | { kind: "recovery"; codes: string[]; accessToken: string };

function loginError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return he.auth.invalidCredentials;
    if (e.status === 429) return he.auth.tooMany;
  }
  return errorMessage(e);
}

export function Login() {
  const { startSession, idleLogout } = useAuth();
  const [step, setStep] = useState<Step>(() => {
    const t = takeInvite();
    return t ? { kind: "invite", token: t } : { kind: "credentials" };
  });
  return (
    <div className="auth-wrap">
      <div className="card auth-card stack">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">⛨</span>
          <span>{he.app.name}<small>{he.app.tagline}</small></span>
        </div>
        {idleLogout && step.kind === "credentials" && <Notice kind="info">{he.auth.idleLogout}</Notice>}
        {step.kind === "credentials" && <Credentials onStep={setStep} />}
        {step.kind === "invite" && <Invite token={step.token} onStep={setStep} />}
        {step.kind === "mfa" && <Mfa token={step.token} onDone={startSession} onBack={() => setStep({ kind: "credentials" })} />}
        {step.kind === "setup" && <Setup token={step.token} onStep={setStep} onBack={() => setStep({ kind: "credentials" })} />}
        {step.kind === "recovery" && <Recovery codes={step.codes} onContinue={() => startSession(step.accessToken)} />}
      </div>
    </div>
  );
}

function Credentials({ onStep }: { onStep: (s: Step) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await post<StepToken>("/auth/login", { email, password, client: "web", device_name: navigator.userAgent.slice(0, 100) }, { noAuth: true });
      onStep(r.status === "mfa_required" ? { kind: "mfa", token: r.token } : { kind: "setup", token: r.token });
    } catch (err) {
      setError(loginError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <h1>{he.auth.loginTitle}</h1>
      {error && <ErrorBox message={error} />}
      <Field id="email" label={he.auth.email}>
        <input id="email" className="input ltr" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field id="password" label={he.auth.password}>
        <input id="password" className="input ltr" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <button className="btn primary" disabled={busy || !email || !password}>{he.auth.login}</button>
    </form>
  );
}

function Invite({ token, onStep }: { token: string; onStep: (s: Step) => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await post<StepToken>("/auth/accept-invite", { token, password }, { noAuth: true });
      onStep({ kind: "setup", token: r.token });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 400 ? he.auth.inviteInvalid : err instanceof ApiError && err.status === 422 ? he.auth.inviteWeak : loginError(err));
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <h1>{he.auth.inviteTitle}</h1>
      <p className="muted">{he.auth.inviteIntro}</p>
      {error && <ErrorBox message={error} />}
      <Field id="new-password" label={he.auth.password}>
        <input id="new-password" className="input ltr" type="password" required minLength={12} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <button className="btn primary" disabled={busy || password.length < 12}>{he.auth.setPassword}</button>
    </form>
  );
}

function Mfa({ token, onDone, onBack }: { token: string; onDone: (access: string) => Promise<void>; onBack: () => void }) {
  const [useRecovery, setUseRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const body = useRecovery ? { recovery_code: code.trim() } : { code: code.trim() };
      const s = await post<Session>("/auth/2fa/verify", body, { token });
      await onDone(s.access_token);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? he.auth.invalidCode : loginError(err));
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <h1>{he.auth.mfaTitle}</h1>
      <p className="muted">{he.auth.mfaPrompt}</p>
      {error && <ErrorBox message={error} />}
      <Field id="code" label={useRecovery ? he.auth.recoveryCode : he.auth.code}>
        <input id="code" className="input code" autoFocus autoComplete="one-time-code" inputMode={useRecovery ? "text" : "numeric"}
          maxLength={useRecovery ? 11 : 6} value={code} onChange={(e) => setCode(e.target.value)} />
      </Field>
      <button className="btn primary" disabled={busy || code.trim().length < (useRecovery ? 11 : 6)}>{he.auth.verify}</button>
      <button type="button" className="link-btn" onClick={() => { setUseRecovery(!useRecovery); setCode(""); setError(null); }}>
        {useRecovery ? he.auth.useApp : he.auth.useRecovery}
      </button>
      <button type="button" className="link-btn" onClick={onBack}>{he.auth.back}</button>
    </form>
  );
}

function Setup({ token, onStep, onBack }: { token: string; onStep: (s: Step) => void; onBack: () => void }) {
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    post<TotpSetup>("/auth/2fa/setup", undefined, { token })
      .then(async (s) => {
        if (!alive) return;
        setSetup(s);
        // Rendered in the browser: the secret never goes to a third-party QR service.
        setQr(await QRCode.toDataURL(s.otpauth_uri, { margin: 1, width: 256 }));
      })
      .catch((e) => alive && setError(loginError(e)));
    return () => { alive = false; };
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const s = await post<Session>("/auth/2fa/enable", { code: code.trim() }, { token });
      onStep({ kind: "recovery", codes: s.recovery_codes ?? [], accessToken: s.access_token });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? he.auth.invalidCode : loginError(err));
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <h1>{he.auth.setupTitle}</h1>
      <p className="muted">{he.auth.setupIntro}</p>
      {error && <ErrorBox message={error} />}
      {qr && <img className="qr" src={qr} alt={he.auth.qrAlt} />}
      {setup && (
        <div className="stack" style={{ gap: "var(--space-2)" }}>
          <span className="small muted">{he.auth.manualKey}</span>
          <code className="secret ltr" data-testid="totp-secret">{setup.secret}</code>
        </div>
      )}
      <Field id="code" label={he.auth.code}>
        <input id="code" className="input code" autoComplete="one-time-code" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
      </Field>
      <button className="btn primary" disabled={busy || !setup || code.trim().length < 6}>{he.auth.enable}</button>
      <button type="button" className="link-btn" onClick={onBack}>{he.auth.back}</button>
    </form>
  );
}

function Recovery({ codes, onContinue }: { codes: string[]; onContinue: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(codes.join("\n")); setCopied(true); } catch { /* clipboard blocked */ }
  }
  return (
    <div className="stack">
      <h1>{he.auth.recoveryTitle}</h1>
      <p className="muted">{he.auth.recoveryIntro}</p>
      <ul className="codes" aria-label={he.auth.recoveryTitle}>{codes.map((c) => <li key={c}>{c}</li>)}</ul>
      <button className="btn" onClick={copy}>{copied ? he.common.copied : he.common.copy}</button>
      <label className="row">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <span>{he.auth.recoverySaved}</span>
      </label>
      <button className="btn primary" disabled={!saved} onClick={onContinue}>{he.auth.continue}</button>
    </div>
  );
}
