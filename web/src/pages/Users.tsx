import { useState, type FormEvent } from "react";
import { ApiError, get, patch, post } from "../api/client";
import type { Invite, Role, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Confirm, ErrorBox, Field, Modal, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatDateTime } from "../lib/format";
import { errorMessage, useAsync } from "../lib/useAsync";

const ROLES = Object.keys(he.role) as Role[];

function actionError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 409) return e.detail === "User already exists" ? he.users.exists : he.users.conflict;
    if (e.status === 403) return he.common.forbidden;
  }
  return errorMessage(e);
}

export function Users() {
  const { user: me } = useAuth();
  const { data, error, loading, reload } = useAsync(() => get<User[]>("/users"), []);
  const [creating, setCreating] = useState(false);
  const [invite, setInvite] = useState<{ title: string; value: Invite } | null>(null);
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function change(u: User, body: Partial<Pick<User, "role" | "is_active">>) {
    setMsg(null);
    try { await patch(`/users/${u.id}`, body); reload(); } catch (e) { setMsg(actionError(e)); }
  }

  async function doReset() {
    if (!resetFor) return;
    try {
      const inv = await post<Invite>(`/users/${resetFor.id}/reset-credentials`);
      setInvite({ title: he.users.resetTitle, value: inv });
      reload();
    } catch (e) { setMsg(actionError(e)); }
    setResetFor(null);
  }

  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorBox message={error ?? he.common.genericError} onRetry={reload} />;
  return (
    <div className="stack">
      <div className="page-head">
        <h1>{he.users.title}</h1>
        <button className="btn primary" onClick={() => setCreating(true)}>{he.users.create}</button>
      </div>
      {msg && <Notice kind="error">{msg}</Notice>}
      <div className="card table-wrap"><table className="table">
        <thead><tr><th>{he.users.name}</th><th>{he.users.email}</th><th>{he.users.role}</th><th>{he.users.twoFactor}</th><th>{he.users.lastLogin}</th><th>{he.users.active}</th><th>{he.common.actions}</th></tr></thead>
        <tbody>{data.map((u) => (
          <tr key={u.id}>
            <td data-label={he.users.name} dir="auto">{u.display_name}</td>
            <td data-label={he.users.email}><bdi className="ltr">{u.email}</bdi></td>
            <td data-label={he.users.role}>
              <select className="input" aria-label={`${he.users.role}: ${u.email}`} value={u.role} disabled={u.id === me?.id}
                onChange={(e) => void change(u, { role: e.target.value as Role })}>
                {ROLES.map((r) => <option key={r} value={r}>{he.role[r]}</option>)}
              </select>
            </td>
            <td data-label={he.users.twoFactor}><Badge kind={u.totp_enabled ? "ok" : "medium"}>{u.totp_enabled ? he.users.twoFactorOn : he.users.twoFactorOff}</Badge></td>
            <td data-label={he.users.lastLogin}>{u.last_login_at ? formatDateTime(u.last_login_at) : he.common.never}</td>
            <td data-label={he.users.active}><Badge kind={u.is_active ? "ok" : ""}>{u.is_active ? he.common.yes : he.common.no}</Badge></td>
            <td>
              <div className="row">
                <button className="btn" disabled={u.id === me?.id} onClick={() => void change(u, { is_active: !u.is_active })}>{u.is_active ? he.users.deactivate : he.users.activate}</button>
                <button className="btn" onClick={() => setResetFor(u)}>{he.users.reset}</button>
              </div>
            </td>
          </tr>))}</tbody>
      </table></div>
      {creating && <CreateUser onClose={() => setCreating(false)} onCreated={(inv) => { setCreating(false); setInvite({ title: he.users.inviteTitle, value: inv }); reload(); }} />}
      {invite && <InviteDialog title={invite.title} invite={invite.value} onClose={() => setInvite(null)} />}
      {resetFor && <Confirm title={he.users.reset} message={he.users.resetWarn} confirmLabel={he.users.reset} danger onConfirm={doReset} onClose={() => setResetFor(null)} />}
    </div>
  );
}

function CreateUser({ onClose, onCreated }: { onClose: () => void; onCreated: (i: Invite) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("reviewer");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { onCreated(await post<Invite>("/users", { email, display_name: name, role })); }
    catch (err) { setError(actionError(err)); setBusy(false); }
  }
  return (
    <Modal title={he.users.create} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        {error && <ErrorBox message={error} />}
        <Field id="u-email" label={he.users.email}><input id="u-email" className="input ltr" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field id="u-name" label={he.users.name}><input id="u-name" className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field id="u-role" label={he.users.role}>
          <select id="u-role" className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => <option key={r} value={r}>{he.role[r]}</option>)}
          </select>
        </Field>
        <button className="btn primary" disabled={busy || !email}>{he.users.create}</button>
      </form>
    </Modal>
  );
}

function InviteDialog({ title, invite, onClose }: { title: string; invite: Invite; onClose: () => void }) {
  const link = `${window.location.origin}/?invite=${invite.token}`;
  const [copied, setCopied] = useState(false);
  async function copy() { try { await navigator.clipboard.writeText(link); setCopied(true); } catch { /* blocked */ } }
  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        <Notice kind="warn">{he.users.inviteHint}</Notice>
        <code className="secret ltr" data-testid="invite-link">{link}</code>
        <div className="row">
          <button className="btn primary" onClick={copy}>{copied ? he.common.copied : he.common.copy}</button>
          <button className="btn" onClick={onClose}>{he.common.close}</button>
        </div>
      </div>
    </Modal>
  );
}
