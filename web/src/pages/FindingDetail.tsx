import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, blobUrl, get, post } from "../api/client";
import type { Decision, DismissReason, FindingDetail } from "../api/types";
import { Badge, ErrorBox, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatDateTime, formatPercent } from "../lib/format";
import { errorMessage, useAsync } from "../lib/useAsync";

export function FindingDetailPage() {
  const { id = "" } = useParams();
  const { data, error, loading, reload } = useAsync(() => get<FindingDetail>(`/findings/${id}`), [id]);
  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorBox message={error ?? he.common.genericError} onRetry={reload} />;
  return (
    <div className="stack">
      <div className="page-head">
        <h1>{he.findings.detailTitle}</h1>
        <Link className="btn" to="/findings">{he.findings.back}</Link>
      </div>
      <Notice kind="info">{he.findings.humanOnly}</Notice>
      <div className="grid cols-2">
        <section className="card stack">
          <div className="row">
            <Badge kind={data.severity}>{he.severity[data.severity]}</Badge>
            <Badge>{he.kind[data.kind as keyof typeof he.kind] ?? data.kind}</Badge>
            <Badge kind="info">{he.status[data.status]}</Badge>
            <bdi className="muted">{he.findings.score}: {formatPercent(data.score)}</bdi>
            {data.adjusted_score != null && <bdi className="muted">· {he.findings.adjusted}: {formatPercent(data.adjusted_score)}</bdi>}
          </div>
          <div><h3>{he.findings.reason}</h3><p>{data.reason}</p></div>
          {data.score <= 0.6 && data.kind === "uniform" && <p className="small muted">{he.findings.lowConfidence}</p>}
          {(data.learning?.length ?? 0) > 0 && (
            <div className="stack" style={{ gap: "var(--gap-2)" }}>
              <h3>{he.findings.learningTitle}</h3>
              <ul className="small">{data.learning!.map((r) => <li key={r}>{r}</li>)}</ul>
              <p className="small muted">{he.findings.learningNote}</p>
            </div>
          )}
          {data.snippet && <div><h3>{he.findings.evidence}</h3><p className="secret" dir="auto">{data.snippet}</p></div>}
          <p className="small muted">
            {he.findings.source}: {he.source[(data.source ?? "text") as keyof typeof he.source] ?? data.source}
            {" · "}{he.findings.engine}: <bdi>{data.engine_version}</bdi>
          </p>
          <p>
            <span>{he.platform[data.platform as keyof typeof he.platform] ?? data.platform}</span>{" "}
            <bdi className="ltr">@{data.username}</bdi>
            {data.posted_at && <span className="muted"> · {formatDateTime(data.posted_at)}</span>}
          </p>
          {data.post_url && <p><bdi className="ltr small">{data.post_url}</bdi></p>}
        </section>
        <section className="card stack">
          <h2>{he.findings.postText}</h2>
          {data.post_text ? <p className="secret" dir="auto" style={{ whiteSpace: "pre-wrap" }}>{data.post_text}</p> : <p className="muted">{he.findings.noText}</p>}
          {data.media.length > 0 && <h3>{he.findings.images}</h3>}
          <div className="stack">{data.media.filter((m) => m.kind === "image").map((m) => <Evidence key={m.index} findingId={data.id} index={m.index} />)}</div>
        </section>
      </div>
      <DecisionPanel finding={data} onDone={reload} />
      <section className="card">
        <h2>{he.findings.history}</h2>
        {data.history.length === 0 ? <p className="muted">{he.findings.noHistory}</p> : (
          <ul className="list">
            {data.history.map((h, i) => (
              <li key={i}>
                <div>
                  <strong>{he.decision[h.decision]}</strong>
                  {h.reason && <span className="muted"> · {he.dismissReason[h.reason]}</span>}
                  {h.note && <p dir="auto">{h.note}</p>}
                </div>
                <div className="small muted">{h.reviewer} · {formatDateTime(h.decided_at)}</div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** Images stay hidden until the reviewer asks: viewing is audited server-side and nothing is cached. */
function Evidence({ findingId, index }: { findingId: string; index: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function show() {
    setBusy(true); setFailed(false);
    try { setUrl(await blobUrl(`/findings/${findingId}/media/${index}`)); } catch { setFailed(true); }
    setBusy(false);
  }
  if (url) {
    return (
      <figure className="stack" style={{ margin: 0 }}>
        <img src={url} alt={`${he.findings.images} ${index + 1}`} style={{ maxInlineSize: "100%", borderRadius: "var(--round-s)" }} />
        <button className="btn" onClick={() => setUrl(null)}>{he.findings.hideImage}</button>
      </figure>
    );
  }
  return (
    <div className="stack">
      <p className="muted small">{he.findings.imageHidden}</p>
      {failed && <ErrorBox message={he.findings.imageFailed} />}
      <button className="btn" onClick={show} disabled={busy}>{he.findings.showImage}</button>
    </div>
  );
}

const REASONS = Object.keys(he.dismissReason) as DismissReason[];

function DecisionPanel({ finding, onDone }: { finding: FindingDetail; onDone: () => void }) {
  const nav = useNavigate();
  const [choice, setChoice] = useState<Decision | null>(null);
  const [reason, setReason] = useState<DismissReason>("not_relevant");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!choice) return;
    setBusy(true); setError(null);
    try {
      await post(`/findings/${finding.id}/decision`, {
        decision: choice, ...(choice === "dismissed" ? { reason } : {}), ...(note.trim() ? { note: note.trim() } : {}),
      });
      setSaved(true); setChoice(null); setNote("");
      onDone();
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? he.common.forbidden : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack">
      <h2>{he.findings.decide}</h2>
      {saved && <Notice kind="ok">{he.findings.saved} <button className="link-btn" onClick={() => nav("/findings")}>{he.findings.next}</button></Notice>}
      {error && <ErrorBox message={error} />}
      <div className="row" role="group" aria-label={he.findings.decide}>
        <button className={`btn ${choice === "confirmed" ? "primary" : ""}`} aria-pressed={choice === "confirmed"} onClick={() => setChoice("confirmed")}>{he.findings.confirm}</button>
        <button className={`btn ${choice === "dismissed" ? "primary" : ""}`} aria-pressed={choice === "dismissed"} onClick={() => setChoice("dismissed")}>{he.findings.dismiss}</button>
        <button className={`btn ${choice === "escalated" ? "primary" : ""}`} aria-pressed={choice === "escalated"} onClick={() => setChoice("escalated")}>{he.findings.escalate}</button>
      </div>
      {choice && (
        <form className="stack" onSubmit={submit}>
          {choice === "dismissed" && (
            <label className="field"><span>{he.findings.reasonLabel}</span>
              <select className="input" value={reason} onChange={(e) => setReason(e.target.value as DismissReason)}>
                {REASONS.map((r) => <option key={r} value={r}>{he.dismissReason[r]}</option>)}
              </select></label>
          )}
          <label className="field"><span>{he.findings.noteLabel}</span>
            <textarea className="input" rows={3} maxLength={2000} dir="auto" value={note} onChange={(e) => setNote(e.target.value)} /></label>
          <button className="btn primary" disabled={busy}>{he.common.save}</button>
        </form>
      )}
    </section>
  );
}
