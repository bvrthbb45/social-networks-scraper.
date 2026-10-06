import { useState } from "react";
import { useAuth } from "../../auth/AuthContext";
import { Notice } from "../../components/ui";
import { he } from "../../i18n/he";
import { takeInvite } from "../../lib/invite";
import { CredentialsStep, InviteStep, MfaStep, RecoveryStep, SetupStep, type Step } from "./steps";

const start = (): Step => {
  const token = takeInvite(); // an invitation link opens straight on "choose a password"
  return token ? { kind: "invite", token } : { kind: "credentials" };
};

export function Login() {
  const { startSession, idleLogout } = useAuth();
  const [step, setStep] = useState<Step>(start);
  const restart = () => setStep({ kind: "credentials" });

  return (
    <div className="auth-wrap">
      <div className="card auth-card stack">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ⛨
          </span>
          <span>
            {he.app.name}
            <small>{he.app.tagline}</small>
          </span>
        </div>
        {idleLogout && step.kind === "credentials" && <Notice kind="info">{he.auth.idleLogout}</Notice>}
        {step.kind === "credentials" && <CredentialsStep go={setStep} />}
        {step.kind === "invite" && <InviteStep token={step.token} go={setStep} />}
        {step.kind === "mfa" && <MfaStep token={step.token} done={startSession} back={restart} />}
        {step.kind === "setup" && <SetupStep token={step.token} go={setStep} back={restart} />}
        {step.kind === "recovery" && <RecoveryStep codes={step.codes} proceed={() => startSession(step.accessToken)} />}
      </div>
    </div>
  );
}
