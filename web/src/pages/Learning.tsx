import { useState, type FormEvent } from "react";
import { ApiError, del, get, post } from "../api/client";
import type { GoldenCase, LearningModel, LearningStatus, TermStat, TermSuggestion } from "../api/types";
import { Badge, Confirm, ErrorBox, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatNumber, formatPercent } from "../lib/format";
import { errorMessage, useAsync } from "../lib/useAsync";

const L = he.learning;

function learningError(e: unknown): string {
  if (e instanceof ApiError && L.errors[e.detail]) return L.errors[e.detail];
  if (e instanceof ApiError && e.status === 403) return he.common.forbidden;
  return errorMessage(e);
}

export function Learning() {
  const status = useAsync(() => get<LearningStatus>("/learning/status"), []);
  const models = useAsync(() => get<LearningModel[]>("/learning/models"), []);
  const [msg, setMsg] = useState<{ kind: "ok" | "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmRollback, setConfirmRollback] = useState(false);

  const refresh = () => { status.reload(); models.reload(); };

  async function run(action: () => Promise<unknown>, okText?: string) {
    setBusy(true);
    setMsg(null);
    try {
      await action();
      if (okText) setMsg({ kind: "ok", text: okText });
      refresh();
    } catch (e) {
      setMsg({ kind: "error", text: learningError(e) });
    } finally {
      setBusy(false);
    }
  }

  if (status.loading && !status.data) return <Spinner />;
  if (status.error || !status.data) return <ErrorBox message={status.error ?? he.common.genericError} onRetry={status.reload} />;
  const s = status.data;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>{L.title}</h1>
        <button className="btn primary" disabled={busy} onClick={() => void run(() => post("/learning/train"), L.trained)}>{L.train}</button>
      </div>
      <Notice kind="info">{L.intro}</Notice>
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}

      <div className="grid cols-4">
        <Stat label={L.labels} value={s.labels} />
        <Stat label={L.positives} value={s.positives} />
        <Stat label={L.needed} value={s.min_labels} />
        <Stat label={he.learning.golden} value={s.golden_cases} />
      </div>

      <section className="card stack">
        <div className="row spread">
          <h2>{L.active}</h2>
          {s.active && <button className="btn danger" disabled={busy} onClick={() => setConfirmRollback(true)}>{L.rollback}</button>}
        </div>
        {s.active ? <p>{L.version} <bdi>{s.active.version}</bdi> · <bdi>{formatNumber(s.active.trained_on)}</bdi> {L.labels}</p> : <p className="muted">{L.noActive}</p>}
      </section>

      <section className="card stack">
        <h2>{L.models}</h2>
        <p className="muted small">{L.twoPerson(String(s.required_approvals))} {L.shadowHint}</p>
        {models.data && models.data.length > 0 && (
          <div className="table-wrap"><table className="table">
            <thead><tr>
              <th>{L.version}</th><th>{L.state}</th><th className="num">{L.baseline}</th><th className="num">{L.modelAuc}</th><th className="num">{L.approvals}</th><th>{he.common.actions}</th>
            </tr></thead>
            <tbody>{models.data.map((m) => <ModelRow key={m.id} m={m} need={s.required_approvals} busy={busy} run={run} />)}</tbody>
          </table></div>
        )}
      </section>

      <Terms />
      <Suggestions onAdded={() => setMsg({ kind: "ok", text: L.added })} />
      <Golden onChange={refresh} />

      {confirmRollback && (
        <Confirm title={L.rollbackTitle} message={L.rollbackWarn} confirmLabel={L.rollback} danger busy={busy}
          onConfirm={() => { setConfirmRollback(false); void run(() => post("/learning/rollback"), L.rolledBack); }}
          onClose={() => setConfirmRollback(false)} />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="card stat"><div className="label">{label}</div><div className="value"><bdi>{formatNumber(value)}</bdi></div></div>;
}

function ModelRow({ m, need, busy, run }: { m: LearningModel; need: number; busy: boolean; run: (a: () => Promise<unknown>, ok?: string) => Promise<void> }) {
  const open = m.status === "candidate" || m.status === "shadow";
  const auc = (v: number | null | undefined) => (v == null ? "—" : formatPercent(v));
  return (
    <tr>
      <td data-label={L.version}><bdi>{m.version}</bdi></td>
      <td data-label={L.state}>
        <Badge kind={m.status === "active" ? "ok" : m.status === "retired" ? "" : "info"}>{L.states[m.status] ?? m.status}</Badge>
        {m.note && <div className="small muted">{L.notes[m.note] ?? m.note}</div>}
        {(m.metrics?.blockers ?? []).map((b) => <div key={b} className="small neg">{L.errors[b] ?? b}</div>)}
      </td>
      <td className="num" data-label={L.baseline}><bdi>{auc(m.metrics?.baseline_auc)}</bdi></td>
      <td className="num" data-label={L.modelAuc}><bdi>{auc(m.metrics?.model_auc)}</bdi></td>
      <td className="num" data-label={L.approvals}><bdi>{m.approvals}/{need}</bdi></td>
      <td>
        {open && (
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => void run(() => post(`/learning/models/${m.id}/approve`))}>{L.approve}</button>
            {m.status === "candidate" && <button className="btn" disabled={busy} onClick={() => void run(() => post(`/learning/models/${m.id}/shadow`))}>{L.shadow}</button>}
            <button className="btn primary" disabled={busy} onClick={() => void run(() => post(`/learning/models/${m.id}/activate`))}>{L.activate}</button>
          </div>
        )}
      </td>
    </tr>
  );
}

function Terms() {
  const { data, error, loading, reload } = useAsync(() => get<TermStat[]>("/learning/terms"), []);
  return (
    <section className="card stack">
      <h2>{L.terms}</h2>
      {loading && !data ? <Spinner /> : error ? <ErrorBox message={error} onRetry={reload} /> : (data ?? []).length === 0 ? <p className="muted">{L.noTerms}</p> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>{L.term}</th><th className="num">{L.decisions}</th><th className="num">{L.confirmedShare}</th><th /></tr></thead>
          <tbody>{data!.map((t) => (
            <tr key={t.id}>
              <td data-label={L.term} dir="auto">{t.term}</td>
              <td className="num" data-label={L.decisions}><bdi>{t.n}</bdi></td>
              <td className="num" data-label={L.confirmedShare}><bdi>{formatPercent(t.precision)}</bdi></td>
              <td>{t.advice && <Badge kind={t.advice === "effective" ? "ok" : "medium"}>{L.advice[t.advice]}</Badge>}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </section>
  );
}

function Suggestions({ onAdded }: { onAdded: () => void }) {
  const { data, error, loading, reload } = useAsync(() => get<TermSuggestion[]>("/learning/term-suggestions"), []);
  const [err, setErr] = useState<string | null>(null);
  async function add(token: string) {
    setErr(null);
    try { await post("/watchlist", { term: token, kind: "codename", severity: "medium" }); onAdded(); reload(); } catch (e) { setErr(learningError(e)); }
  }
  return (
    <section className="card stack">
      <h2>{L.suggestions}</h2>
      <p className="muted small">{L.suggestionsHint}</p>
      {err && <ErrorBox message={err} />}
      {loading && !data ? <Spinner /> : error ? <ErrorBox message={error} onRetry={reload} /> : (data ?? []).length === 0 ? <p className="muted">{L.noSuggestions}</p> : (
        <ul className="list">{data!.map((s) => (
          <li key={s.token}>
            <div><strong dir="auto">{s.token}</strong>
              <div className="small muted">{L.posts}: <bdi>{s.confirmed_posts}</bdi> · {L.accounts}: <bdi>{s.accounts}</bdi></div></div>
            <button className="btn" onClick={() => void add(s.token)}>{L.addTerm}</button>
          </li>))}</ul>
      )}
    </section>
  );
}

function Golden({ onChange }: { onChange: () => void }) {
  const { data, error, loading, reload } = useAsync(() => get<GoldenCase[]>("/learning/golden"), []);
  const [text, setText] = useState("");
  const [kind, setKind] = useState("codename");
  const [err, setErr] = useState<string | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try { await post("/learning/golden", { text, kind }); setText(""); reload(); onChange(); } catch (x) { setErr(learningError(x)); }
  }
  async function remove(id: string) { await del(`/learning/golden/${id}`); reload(); onChange(); }

  return (
    <section className="card stack">
      <h2>{L.golden}</h2>
      <p className="muted small">{L.goldenHint}</p>
      {err && <ErrorBox message={err} />}
      <form className="row" onSubmit={add}>
        <label className="field" style={{ flex: "1 1 18rem" }}><span>{L.goldenText}</span>
          <input className="input" dir="auto" value={text} onChange={(e) => setText(e.target.value)} /></label>
        <label className="field"><span>{L.goldenKind}</span>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(he.kind).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        <button className="btn primary" disabled={text.trim().length < 3}>{L.addGolden}</button>
      </form>
      {loading && !data ? <Spinner /> : error ? <ErrorBox message={error} onRetry={reload} /> : (data ?? []).length === 0 ? <p className="muted small">{L.noGolden}</p> : (
        <ul className="list">{data!.map((g) => (
          <li key={g.id}><span dir="auto">{g.text} <Badge>{he.kind[g.kind as keyof typeof he.kind] ?? g.kind}</Badge></span>
            <button className="btn danger" onClick={() => void remove(g.id)}>{he.common.delete}</button></li>))}</ul>
      )}
    </section>
  );
}
