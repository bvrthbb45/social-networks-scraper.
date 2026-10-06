import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { ApiError, post } from "../../api/client";
import type { Session, StepToken, TotpSetup } from "../../api/types";
import { ErrorBox, Field } from "../../components/ui";
import { he } from "../../i18n/he";
import { signInError, useSubmit } from "./useSubmit";

export type Step =
  | { kind: "credentials" }
  | { kind: "invite"; token: string }
  | { kind: "mfa"; token: string }
  | { kind: "setup"; token: string }
  | { kind: "recovery"; codes: string[]; accessToken: string };

const next = (r: StepToken): Step => (r.status === "mfa_required" ? { kind: "mfa", token: r.token } : { kind: "setup", token: r.token });

export function CredentialsStep({ go }: { go: (s: Step) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, submit } = useSubmit(async () => {
    const reply = await post<StepToken>(
      "/auth/login",
      { email, password, client: "web", device_name: navigator.userAgent.slice(0, 100) },
      { anonymous: true },
    );
    go(next(reply));
  });
  return (
    <form className="stack" onSubmit={submit} noValidate>
      <h1>{he.auth.loginTitle}</h1>
      {error && <ErrorBox message={error} />}
      <Field id="email" label={he.auth.email}>
        <input id="email" className="input ltr" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field id="password" label={he.auth.password}>
        <input id="password" className="input ltr" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <button className="btn primary" disabled={busy || !email || !password}>
        {he.auth.login}
      </button>
    </form>
  );
}

export function InviteStep({ token, go }: { token: string; go: (s: Step) => void }) {
  const [password, setPassword] = useState("");
  const { busy, error, submit } = useSubmit(
    async () => {
      go(next(await post<StepToken>("/auth/accept-invite", { token, password }, { anonymous: true })));
    },
    (e) => signInError(e, { 400: he.auth.inviteInvalid, 422: he.auth.inviteWeak }),
  );
  return (
    <form className="stack" onSubmit={submit}>
      <h1>{he.auth.inviteTitle}</h1>
      <p className="muted">{he.auth.inviteIntro}</p>
      {error && <ErrorBox message={error} />}
      <Field id="new-password" label={he.auth.password}>
        <input id="new-password" className="input ltr" type="password" minLength={12} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <button className="btn primary" disabled={busy || password.length < 12}>
        {he.auth.setPassword}
      </button>
    </form>
  );
}

export function MfaStep({ token, done, back }: { token: string; done: (accessToken: string) => Promise<void>; back: () => void }) {
  const [recovery, setRecovery] = useState(false);
  const [code, setCode] = useState("");
  const wanted = recovery ? 11 : 6;
  const { busy, error, submit } = useSubmit(
    async () => {
      const body = recovery ? { recovery_code: code.trim() } : { code: code.trim() };
      await done((await post<Session>("/auth/2fa/verify", body, { token })).access_token);
    },
    (e) => signInError(e, { 401: he.auth.invalidCode }),
  );
  const switchMode = () => {
    setRecovery(!recovery);
    setCode("");
  };
  return (
    <form className="stack" onSubmit={submit}>
      <h1>{he.auth.mfaTitle}</h1>
      <p className="muted">{he.auth.mfaPrompt}</p>
      {error && <ErrorBox message={error} />}
      <Field id="code" label={recovery ? he.auth.recoveryCode : he.auth.code}>
        <input id="code" className="input code" autoFocus autoComplete="one-time-code" inputMode={recovery ? "text" : "numeric"} maxLength={wanted} value={code} onChange={(e) => setCode(e.target.value)} />
      </Field>
      <button className="btn primary" disabled={busy || code.trim().length < wanted}>
        {he.auth.verify}
      </button>
      <button type="button" className="link-btn" onClick={switchMode}>
        {recovery ? he.auth.useApp : he.auth.useRecovery}
      </button>
      <button type="button" className="link-btn" onClick={back}>
        {he.auth.back}
      </button>
    </form>
  );
}

export function SetupStep({ token, go, back }: { token: string; go: (s: Step) => void; back: () => void }) {
  const [secret, setSecret] = useState<TotpSetup | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [code, setCode] = useState("");

  useEffect(() => {
    let current = true;
    (async () => {
      try {
        const s = await post<TotpSetup>("/auth/2fa/setup", undefined, { token });
        if (!current) return;
        setSecret(s);
        setQr(await QRCode.toDataURL(s.otpauth_uri, { margin: 1, width: 256 })); // drawn locally: the secret never leaves the browser
      } catch (e) {
        if (current) setLoadError(signInError(e));
      }
    })();
    return () => {
      current = false;
    };
  }, [token]);

  const { busy, error, submit } = useSubmit(
    async () => {
      const s = await post<Session>("/auth/2fa/enable", { code: code.trim() }, { token });
      go({ kind: "recovery", codes: s.recovery_codes ?? [], accessToken: s.access_token });
    },
    (e) => (e instanceof ApiError && e.status === 401 ? he.auth.invalidCode : signInError(e)),
  );
  return (
    <form className="stack" onSubmit={submit}>
      <h1>{he.auth.setupTitle}</h1>
      <p className="muted">{he.auth.setupIntro}</p>
      {(loadError ?? error) && <ErrorBox message={(loadError ?? error)!} />}
      {qr && <img className="qr" src={qr} alt={he.auth.qrAlt} />}
      {secret && (
        <div className="stack" style={{ gap: "var(--gap-2)" }}>
          <span className="small muted">{he.auth.manualKey}</span>
          <code className="secret ltr" data-testid="totp-secret">
            {secret.secret}
          </code>
        </div>
      )}
      <Field id="code" label={he.auth.code}>
        <input id="code" className="input code" autoComplete="one-time-code" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
      </Field>
      <button className="btn primary" disabled={busy || !secret || code.trim().length < 6}>
        {he.auth.enable}
      </button>
      <button type="button" className="link-btn" onClick={back}>
        {he.auth.back}
      </button>
    </form>
  );
}

export function RecoveryStep({ codes, proceed }: { codes: string[]; proceed: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      setCopied(true);
    } catch {
      /* clipboard access denied: the codes are on screen anyway */
    }
  };
  return (
    <div className="stack">
      <h1>{he.auth.recoveryTitle}</h1>
      <p className="muted">{he.auth.recoveryIntro}</p>
      <ul className="codes" aria-label={he.auth.recoveryTitle}>
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <button type="button" className="btn" onClick={copy}>
        {copied ? he.common.copied : he.common.copy}
      </button>
      <label className="row">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <span>{he.auth.recoverySaved}</span>
      </label>
      <button type="button" className="btn primary" disabled={!saved} onClick={proceed}>
        {he.auth.continue}
      </button>
    </div>
  );
}
