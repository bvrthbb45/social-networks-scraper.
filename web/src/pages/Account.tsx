import { del, get } from "../api/client";
import type { Device } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, ErrorBox, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatDateTime } from "../lib/format";
import { useAsync } from "../lib/useAsync";

export function Account() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(() => get<Device[]>("/auth/devices"), []);
  async function revoke(id: string) { await del(`/auth/devices/${id}`); reload(); }
  return (
    <div className="stack">
      <div className="page-head"><h1>{he.account.title}</h1></div>
      <section className="card stack">
        <div><strong dir="auto">{user?.display_name}</strong></div>
        <div className="row"><bdi className="ltr">{user?.email}</bdi><Badge kind="info">{user ? he.role[user.role] : ""}</Badge></div>
      </section>
      <section className="card">
        <h2>{he.account.devices}</h2>
        {loading && !data ? <Spinner /> : error || !data ? <ErrorBox message={error ?? he.common.genericError} onRetry={reload} /> : (
          <ul className="list">
            {data.map((d) => (
              <li key={d.id}>
                <div>
                  <strong dir="auto">{d.name || he.account.unnamed}</strong>{" "}
                  <span className="muted small">{d.kind === "android" ? he.account.android : he.account.web}</span>
                  {d.current && <> <Badge kind="ok">{he.account.current}</Badge></>}
                  <div className="small muted">{he.account.lastSeen}: {d.last_seen_at ? formatDateTime(d.last_seen_at) : he.common.never}</div>
                </div>
                {d.revoked_at ? <Badge>{he.account.revoked}</Badge> : !d.current && <button className="btn" onClick={() => void revoke(d.id)}>{he.account.revoke}</button>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
