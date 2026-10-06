import { useState } from "react";
import { get } from "../api/client";
import type { ExpiringConsent, ReportSummary, RetentionStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, ErrorBox, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatDateTime, formatNumber, formatPercent } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const R = he.reports;
const PERIODS = [7, 30, 90, 365];
const kindName = (k: string) => he.kind[k as keyof typeof he.kind] ?? k;

export function Reports() {
  const { user } = useAuth();
  const [days, setDays] = useState(30);
  const summary = useAsync(() => get<ReportSummary>(`/reports/summary?days=${days}`), [days]);
  const retention = useAsync(() => get<RetentionStatus>("/reports/retention"), []);
  return (
    <div className="stack">
      <div className="page-head">
        <h1>{R.title}</h1>
        <label className="field"><span>{R.period}</span>
          <select className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {PERIODS.map((d) => <option key={d} value={d}>{R.days(String(d))}</option>)}
          </select></label>
      </div>
      <Notice kind="info">{R.intro}</Notice>
      {summary.loading && !summary.data ? <Spinner /> : summary.error || !summary.data ? <ErrorBox message={summary.error ?? he.common.genericError} onRetry={summary.reload} /> : <Summary s={summary.data} />}
      {retention.data && <Retention r={retention.data} />}
      {user?.role === "admin" && <Consents />}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="card stat"><div className="label">{label}</div><div className="value"><bdi>{value}</bdi></div></div>;
}

function Counts({ title, data, name = (k: string) => k }: { title: string; data: Record<string, number>; name?: (k: string) => string }) {
  const entries = Object.entries(data);
  return (
    <section className="card">
      <h2>{title}</h2>
      {entries.length === 0 ? <p className="muted">{R.none}</p> : (
        <ul className="list">{entries.map(([k, n]) => <li key={k}><span>{name(k)}</span><bdi>{formatNumber(n)}</bdi></li>)}</ul>
      )}
    </section>
  );
}

function Summary({ s }: { s: ReportSummary }) {
  const falseAlarms = Object.entries(s.false_alarm_by_kind);
  return (
    <>
      <div className="grid cols-4">
        <Stat label={R.created} value={formatNumber(s.findings_created)} />
        <Stat label={R.backlog} value={formatNumber(s.backlog)} />
        <Stat label={R.median} value={s.median_hours_to_decision == null ? "—" : R.hours(String(s.median_hours_to_decision))} />
        <Stat label={R.oldest} value={s.oldest_open_hours == null ? "—" : R.hours(formatNumber(Math.round(s.oldest_open_hours)))} />
      </div>
      <div className="grid cols-3">
        <Counts title={R.decisions} data={s.decisions} name={(k) => he.decision[k as keyof typeof he.decision] ?? k} />
        <Counts title={R.dismissReasons} data={s.dismissal_reasons} name={(k) => he.dismissReason[k as keyof typeof he.dismissReason] ?? k} />
        <Counts title={R.accounts} data={s.accounts_by_status} name={(k) => R.accountStatus[k] ?? k} />
      </div>
      <div className="grid cols-2">
        <Counts title={R.byKind} data={s.created_by_kind} name={kindName} />
        <Counts title={R.bySeverity} data={s.created_by_severity} name={(k) => he.severity[k as keyof typeof he.severity] ?? k} />
      </div>
      <section className="card stack">
        <h2>{R.falseAlarms}</h2>
        {falseAlarms.length === 0 ? <p className="muted">{R.none}</p> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>{he.findings.type}</th><th className="num">{R.decided}</th><th className="num">{R.dismissed}</th><th className="num">{R.rate}</th></tr></thead>
            <tbody>{falseAlarms.map(([k, v]) => (
              <tr key={k}><td data-label={he.findings.type}>{kindName(k)}</td>
                <td className="num" data-label={R.decided}><bdi>{v.decided}</bdi></td>
                <td className="num" data-label={R.dismissed}><bdi>{v.dismissed}</bdi></td>
                <td className="num" data-label={R.rate}><bdi>{formatPercent(v.rate)}</bdi></td></tr>))}</tbody>
          </table></div>
        )}
      </section>
      <div className="grid cols-2">
        <Counts title={R.security} data={Object.fromEntries(Object.entries(s.security_events).filter(([, n]) => n > 0))} name={(k) => R.events[k] ?? k} />
        <section className="card">
          <h2>{R.imports}</h2>
          <ul className="list">
            <li><span>{R.files}</span><bdi>{formatNumber(s.imports.files)}</bdi></li>
            <li><span>{R.rows}</span><bdi>{formatNumber(s.imports.rows)}</bdi></li>
            <li><span>{R.rejectedRows}</span><bdi>{formatNumber(s.imports.rejected_rows)}</bdi></li>
            <li><span>{R.learningModel}</span><span>{s.learning ? R.modelAge(String(s.learning.version), String(s.learning.age_days)) : R.noModel}</span></li>
          </ul>
        </section>
      </div>
    </>
  );
}

function Retention({ r }: { r: RetentionStatus }) {
  return (
    <section className="card">
      <h2>{R.retention}</h2>
      <ul className="list">
        <li><span>{R.retentionDays}</span><bdi>{r.retention_days}</bdi></li>
        <li><span>{R.postsTotal}</span><bdi>{formatNumber(r.posts_total)}</bdi></li>
        <li><span>{R.overdue}</span><span>{r.overdue > 0 ? <Badge kind="high">{r.overdue}</Badge> : <bdi>0</bdi>}</span></li>
        <li><span>{R.dueSoon}</span><bdi>{formatNumber(r.due_within_7_days)}</bdi></li>
        <li><span>{R.oldestPost}</span><bdi>{r.oldest_post_days ?? "—"}</bdi></li>
        <li><span>{R.lastRun}</span><span>{r.last_run ? <>{formatDateTime(r.last_run.at)} · {R.purgedPosts}: <bdi>{r.last_run.counts["purged.posts"] ?? 0}</bdi></> : R.neverRun}</span></li>
      </ul>
    </section>
  );
}

function Consents() {
  const { data, error, loading, reload } = useAsync(() => get<ExpiringConsent[]>("/reports/consents?days=30"), []);
  return (
    <section className="card stack">
      <h2>{R.consents}</h2>
      <p className="muted small">{R.consentsHint}</p>
      {loading && !data ? <Spinner /> : error ? <ErrorBox message={error} onRetry={reload} /> : (data ?? []).length === 0 ? <p className="muted">{R.noConsents}</p> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>{R.soldier}</th><th>{R.ref}</th><th>{R.until}</th><th className="num">{R.daysLeft}</th><th className="num">{he.people.accounts}</th></tr></thead>
          <tbody>{data!.map((c) => (
            <tr key={c.consent_id}>
              <td data-label={R.soldier} dir="auto">{c.soldier}</td>
              <td data-label={R.ref}><bdi className="ltr">{c.ref}</bdi></td>
              <td data-label={R.until}><bdi>{c.valid_until}</bdi></td>
              <td className="num" data-label={R.daysLeft}>{c.days_left < 0 ? <Badge kind="high">{R.expired}</Badge> : <Badge kind={c.days_left <= 7 ? "medium" : "info"}>{c.days_left}</Badge>}</td>
              <td className="num" data-label={he.people.accounts}><bdi>{c.accounts}</bdi></td>
            </tr>))}</tbody>
        </table></div>
      )}
    </section>
  );
}
