import { useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api/client";
import { downloadFile } from "../lib/download";
import type { FindingRow, FindingStatus } from "../api/types";
import { Badge, Empty, ErrorBox, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatDateTime, formatPercent } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const STATUSES: FindingStatus[] = ["new", "escalated", "confirmed", "dismissed"];
const SEVERITIES = ["high", "medium", "low"] as const;
const PAGE = 25;

export function Findings() {
  const [status, setStatus] = useState<FindingStatus>("new");
  const [severity, setSeverity] = useState("");
  const [kind, setKind] = useState("");
  const [platform, setPlatform] = useState("");
  const [order, setOrder] = useState("priority");
  const [page, setPage] = useState(0);
  const { data, error, loading, reload } = useAsync(() => {
    const q = new URLSearchParams({ status_: status, limit: String(PAGE + 1), offset: String(page * PAGE), order });
    if (severity) q.set("severity", severity);
    if (kind) q.set("kind", kind);
    if (platform) q.set("platform", platform);
    return get<FindingRow[]>(`/findings?${q}`);
  }, [status, severity, kind, platform, order, page]);

  const [exportError, setExportError] = useState<string | null>(null);
  async function exportReport() {
    setExportError(null);
    try { await downloadFile("/reports/export/findings?states=confirmed,escalated&days=30", "findings-report.xlsx"); }
    catch { setExportError(he.findings.exportFailed); }
  }

  const reset = (fn: () => void) => { fn(); setPage(0); };
  const rows = loading ? [] : (data ?? []).slice(0, PAGE); // never show another filter's rows
  const hasMore = !loading && (data?.length ?? 0) > PAGE;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>{he.findings.title}</h1>
        <button className="btn" onClick={() => void exportReport()}>{he.findings.exportConfirmed}</button>
      </div>
      <p className="muted small">{he.findings.exportNote}</p>
      {exportError && <ErrorBox message={exportError} />}
      <div className="tabs" role="tablist" aria-label={he.findings.statusTab}>
        {STATUSES.map((s) => (
          <button key={s} role="tab" aria-selected={status === s} onClick={() => reset(() => setStatus(s))}>{he.status[s]}</button>
        ))}
      </div>
      <div className="card">
        <div className="grid cols-3">
          <label className="field"><span>{he.findings.severity}</span>
            <select className="input" value={severity} onChange={(e) => reset(() => setSeverity(e.target.value))}>
              <option value="">{he.common.all}</option>
              {SEVERITIES.map((s) => <option key={s} value={s}>{he.severity[s]}</option>)}
            </select></label>
          <label className="field"><span>{he.findings.type}</span>
            <select className="input" value={kind} onChange={(e) => reset(() => setKind(e.target.value))}>
              <option value="">{he.common.all}</option>
              {Object.entries(he.kind).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
          <label className="field"><span>{he.findings.order}</span>
            <select className="input" value={order} onChange={(e) => reset(() => setOrder(e.target.value))}>
              <option value="priority">{he.findings.orderPriority}</option>
              <option value="uncertain">{he.findings.orderUncertain}</option>
              <option value="newest">{he.findings.orderNewest}</option>
            </select></label>
          <label className="field"><span>{he.findings.platform}</span>
            <select className="input" value={platform} onChange={(e) => reset(() => setPlatform(e.target.value))}>
              <option value="">{he.common.all}</option>
              {Object.entries(he.platform).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
        </div>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!loading && !error && rows.length === 0 && <Empty title={he.findings.empty} />}
      {rows.length > 0 && (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr>
              <th>{he.findings.severity}</th><th>{he.findings.type}</th><th>{he.findings.reason}</th>
              <th>{he.findings.account}</th><th className="num">{he.findings.score}</th><th />
            </tr></thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.id}>
                  <td data-label={he.findings.severity}>
                    <Badge kind={f.severity}>{he.severity[f.severity]}</Badge>
                    {f.lane === "low" && <div><Badge>{he.findings.lowLane}</Badge></div>}
                  </td>
                  <td data-label={he.findings.type}>{he.kind[f.kind as keyof typeof he.kind] ?? f.kind}</td>
                  <td data-label={he.findings.reason}>{f.reason}<div className="small muted">{formatDateTime(f.created_at)}</div></td>
                  <td data-label={he.findings.account}>
                    <span>{he.platform[f.platform as keyof typeof he.platform] ?? f.platform}</span>{" "}
                    <bdi className="ltr">@{f.username}</bdi>
                  </td>
                  <td className="num" data-label={he.findings.score}><bdi>{formatPercent(f.adjusted_score ?? f.score)}</bdi></td>
                  <td><Link className="btn" to={`/findings/${f.id}`}>{he.findings.open}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="row">
        {page > 0 && <button className="btn" onClick={() => setPage(page - 1)}>{he.common.prev}</button>}
        {hasMore && <button className="btn" onClick={() => setPage(page + 1)}>{he.common.loadMore}</button>}
      </div>
    </div>
  );
}
