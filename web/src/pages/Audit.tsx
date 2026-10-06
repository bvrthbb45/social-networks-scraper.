import { useState } from "react";
import { get } from "../api/client";
import type { AuditRow } from "../api/types";
import { Empty, ErrorBox, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatDateTime } from "../lib/format";
import { useAsync } from "../lib/useAsync";

export function Audit() {
  const [action, setAction] = useState("");
  const [extra, setExtra] = useState<AuditRow[]>([]);
  const [more, setMore] = useState(true);
  const { data, error, loading, reload } = useAsync(async () => {
    setExtra([]); setMore(true);
    const q = new URLSearchParams({ limit: "100" });
    if (action.trim()) q.set("action", action.trim());
    return get<AuditRow[]>(`/audit?${q}`);
  }, [action]);

  const rows = loading ? [] : [...(data ?? []), ...extra];
  async function loadMore() {
    const last = rows[rows.length - 1];
    if (!last) return;
    const q = new URLSearchParams({ limit: "100", before_id: String(last.id) });
    if (action.trim()) q.set("action", action.trim());
    const next = await get<AuditRow[]>(`/audit?${q}`);
    setExtra([...extra, ...next]);
    if (next.length < 100) setMore(false);
  }

  return (
    <div className="stack">
      <div className="page-head"><h1>{he.audit.title}</h1></div>
      <Notice kind="info">{he.audit.hint}</Notice>
      <label className="field"><span>{he.audit.action}</span>
        <input className="input ltr" value={action} onChange={(e) => setAction(e.target.value)} placeholder="login.failed" /></label>
      {loading && <Spinner />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!loading && !error && rows.length === 0 && <Empty title={he.audit.empty} />}
      {rows.length > 0 && (
        <div className="card table-wrap"><table className="table">
          <thead><tr><th>{he.audit.time}</th><th>{he.audit.action}</th><th>{he.audit.object}</th><th>{he.audit.ip}</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}>
              <td data-label={he.audit.time}>{formatDateTime(r.created_at)}</td>
              <td data-label={he.audit.action}><bdi className="ltr">{r.action}</bdi></td>
              <td data-label={he.audit.object}><bdi className="ltr small">{r.object_type ? `${r.object_type}:${r.object_id?.slice(0, 8) ?? ""}` : ""}</bdi></td>
              <td data-label={he.audit.ip}><bdi className="ltr">{r.ip ?? ""}</bdi></td>
            </tr>))}</tbody>
        </table></div>
      )}
      {more && rows.length >= 100 && rows.length % 100 === 0 && <button className="btn" onClick={() => void loadMore()}>{he.common.loadMore}</button>}
    </div>
  );
}
