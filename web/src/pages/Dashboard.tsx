import { Link } from "react-router-dom";
import { get } from "../api/client";
import type { Stats } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorBox, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatDateTime, formatNumber } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const sum = (o: Record<string, number> | undefined) => Object.values(o ?? {}).reduce((a, b) => a + b, 0);

export function Dashboard() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(() => get<Stats>("/stats"), []);
  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorBox message={error ?? he.common.genericError} onRetry={reload} />;
  const open = (data.findings_by_status.new ?? 0) + (data.findings_by_status.in_review ?? 0);
  const decided = (data.findings_by_status.confirmed ?? 0) + (data.findings_by_status.dismissed ?? 0) + (data.findings_by_status.escalated ?? 0);
  const canReview = user?.role === "reviewer" || user?.role === "admin";
  return (
    <div className="stack">
      <div className="page-head">
        <h1>{he.dashboard.title}</h1>
        {canReview && <Link className="btn primary" to="/findings">{he.dashboard.toQueue}</Link>}
      </div>
      <Notice kind="info">{he.dashboard.note}</Notice>
      <div className="grid cols-4">
        <Stat label={he.dashboard.openFindings} value={open} />
        <Stat label={he.dashboard.high} value={data.open_by_severity.high ?? 0} danger />
        <Stat label={he.dashboard.decided} value={decided} />
        <Stat label={he.dashboard.accounts} value={sum(data.accounts_by_status)} />
      </div>
      <div className="grid cols-2">
        <section className="card">
          <h2>{he.dashboard.byKind}</h2>
          {Object.keys(data.open_by_kind).length === 0 ? <p className="muted">{he.common.none}</p> : (
            <ul className="list">
              {Object.entries(data.open_by_kind).map(([k, n]) => (
                <li key={k}><span>{he.kind[k as keyof typeof he.kind] ?? k}</span><bdi>{formatNumber(n)}</bdi></li>
              ))}
            </ul>
          )}
        </section>
        <section className="card">
          <h2>{he.dashboard.accounts}</h2>
          <ul className="list">
            <li><span>{he.dashboard.openAccounts}</span><bdi>{formatNumber(data.accounts_by_status.open ?? 0)}</bdi></li>
            <li><span>{he.dashboard.closedAccounts}</span><bdi>{formatNumber(data.accounts_by_status.closed ?? 0)}</bdi></li>
            <li><span>{he.dashboard.lastImport}</span><span>{data.last_import_at ? formatDateTime(data.last_import_at) : he.common.never}</span></li>
          </ul>
        </section>
      </div>
    </div>
  );
}

function Stat({ label, value, danger = false }: { label: string; value: number; danger?: boolean }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className={`value ${danger && value > 0 ? "neg" : ""}`}><bdi>{formatNumber(value)}</bdi></div>
    </div>
  );
}
