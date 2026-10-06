import { useState } from "react";
import { del, get, post } from "../api/client";
import type { SoldierRow } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Confirm, Empty, ErrorBox, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { errorMessage, useAsync } from "../lib/useAsync";

type Pending = { kind: "revoke"; id: string } | { kind: "erase"; id: string } | null;

export function People() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { data, error, loading, reload } = useAsync(() => get<SoldierRow[]>("/soldiers"), []);
  const [pending, setPending] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function run() {
    if (!pending) return;
    setBusy(true);
    try {
      if (pending.kind === "revoke") { await post(`/consents/${pending.id}/revoke`); setMsg({ kind: "ok", text: he.people.revoked }); }
      else { await del(`/soldiers/${pending.id}`); setMsg({ kind: "ok", text: he.people.erased }); }
      setPending(null);
      reload();
    } catch (e) {
      setMsg({ kind: "error", text: errorMessage(e) });
      setPending(null);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorBox message={error ?? he.common.genericError} onRetry={reload} />;
  return (
    <div className="stack">
      <div className="page-head"><h1>{he.people.title}</h1></div>
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      {data.length === 0 ? <Empty title={he.people.empty} /> : (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr><th>{he.people.name}</th><th>{he.people.unit}</th><th className="num">{he.people.accounts}</th><th>{he.people.consents}</th>{isAdmin && <th>{he.common.actions}</th>}</tr></thead>
            <tbody>
              {data.map((s) => (
                <tr key={s.id}>
                  <td data-label={he.people.name} dir="auto">{s.full_name}</td>
                  <td data-label={he.people.unit} dir="auto">{s.unit ?? ""}</td>
                  <td className="num" data-label={he.people.accounts}><bdi>{s.accounts}</bdi></td>
                  <td data-label={he.people.consents}>
                    <div className="stack" style={{ gap: "var(--gap-2)" }}>
                      {s.consents.map((c) => (
                        <div key={c.id} className="row">
                          <Badge kind={c.status === "active" ? "ok" : "medium"}>{he.people.consentStatus[c.status as keyof typeof he.people.consentStatus] ?? c.status}</Badge>
                          <bdi className="ltr small">{c.ref}</bdi>
                          <span className="small muted">{he.people.until} <bdi>{c.valid_until}</bdi></span>
                          {isAdmin && c.status === "active" && (
                            <button className="link-btn" onClick={() => setPending({ kind: "revoke", id: c.id })}>{he.people.revoke}</button>
                          )}
                        </div>
                      ))}
                    </div>
                  </td>
                  {isAdmin && <td><button className="btn danger" onClick={() => setPending({ kind: "erase", id: s.id })}>{he.people.erase}</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pending && (
        <Confirm
          title={pending.kind === "revoke" ? he.people.revokeTitle : he.people.eraseTitle}
          message={pending.kind === "revoke" ? he.people.revokeWarn : he.people.eraseWarn}
          confirmLabel={pending.kind === "revoke" ? he.people.revoke : he.people.erase}
          danger busy={busy} onConfirm={run} onClose={() => setPending(null)}
        />
      )}
    </div>
  );
}
