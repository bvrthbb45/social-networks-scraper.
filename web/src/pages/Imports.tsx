import { useRef, useState } from "react";
import { ApiError, get, upload } from "../api/client";
import type { ImportRow, ImportSummary } from "../api/types";
import { Badge, ErrorBox, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { formatDateTime, formatNumber } from "../lib/format";
import { errorMessage, useAsync } from "../lib/useAsync";
import { useAuth } from "../auth/AuthContext";

function fileError(e: unknown): string {
  if (e instanceof ApiError) {
    const code = e.detail.split(":")[0];
    if (he.imports.errors[code]) return he.imports.errors[code] + (e.detail.startsWith("missing_columns:") ? ` (${e.detail.split(":")[1]})` : "");
    if (e.status === 413) return he.imports.errors.file_too_large;
    if (e.status === 403) return he.common.forbidden;
  }
  return errorMessage(e);
}

export function Imports() {
  const { user } = useAuth();
  const canUpload = user?.role === "uploader" || user?.role === "admin";
  const history = useAsync(() => get<ImportRow[]>("/imports"), []);
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(dryRun: boolean) {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("dry_run", String(dryRun));
      const r = await upload<ImportSummary>("/imports/roster", form);
      setResult(r);
      if (!dryRun) { history.reload(); setFile(null); if (input.current) input.current.value = ""; }
    } catch (e) {
      setResult(null);
      setError(fileError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="page-head"><h1>{he.imports.title}</h1></div>
      {canUpload && (
        <section className="card stack">
          <h2>{he.imports.roster}</h2>
          <p className="muted small">{he.imports.previewHint}</p>
          {error && <ErrorBox message={error} />}
          <label className="field">
            <span>{he.imports.chooseFile}</span>
            <input ref={input} className="input" type="file" accept=".xlsx" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null); }} />
          </label>
          <div className="row">
            <button className="btn" disabled={!file || busy} onClick={() => send(true)}>{he.imports.preview}</button>
            {result?.dry_run && <button className="btn primary" disabled={busy} onClick={() => send(false)}>{he.imports.commit}</button>}
          </div>
          {result && <Summary r={result} />}
        </section>
      )}
      <section className="card">
        <h2>{he.imports.history}</h2>
        {history.loading && !history.data ? <Spinner /> : history.error ? <ErrorBox message={history.error} onRetry={history.reload} /> : (history.data ?? []).length === 0 ? <p className="muted">{he.common.none}</p> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>{he.imports.file}</th><th>{he.imports.at}</th><th className="num">{he.imports.rows}</th><th className="num">{he.imports.rejected}</th></tr></thead>
            <tbody>{history.data!.map((i) => (
              <tr key={i.id}>
                <td data-label={he.imports.file}><bdi className="ltr">{i.filename}</bdi></td>
                <td data-label={he.imports.at}>{formatDateTime(i.uploaded_at)}</td>
                <td className="num" data-label={he.imports.rows}><bdi>{formatNumber(i.rows_total)}</bdi></td>
                <td className="num" data-label={he.imports.rejected}><bdi>{formatNumber(i.rows_rejected)}</bdi></td>
              </tr>))}</tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}

function Summary({ r }: { r: ImportSummary }) {
  const rejected = Object.entries(r.rejected);
  return (
    <div className="stack" aria-live="polite">
      <Notice kind={r.dry_run ? "info" : "ok"}>{r.dry_run ? he.imports.previewResult : he.imports.done}</Notice>
      {r.duplicate_file && <Notice kind="warn">{he.imports.duplicateFile}</Notice>}
      {r.phone_columns_ignored > 0 && <Notice kind="info">{he.imports.phones(String(r.phone_columns_ignored))}</Notice>}
      <ul className="list">
        <li><span>{he.imports.rows}</span><bdi>{r.rows_total}</bdi></li>
        <li><span>{he.imports.soldiersCreated}</span><bdi>{r.soldiers_created}</bdi></li>
        <li><span>{he.imports.accountsCreated}</span><bdi>{r.accounts_created}</bdi></li>
        <li><span>{he.imports.accountsUpdated}</span><bdi>{r.accounts_updated}</bdi></li>
        <li><span>{he.imports.unchanged}</span><bdi>{r.unchanged}</bdi></li>
      </ul>
      {rejected.length > 0 && (
        <div className="stack">
          <h3>{he.imports.rejected}</h3>
          <ul className="list">
            {rejected.map(([code, lines]) => (
              <li key={code}>
                <div>{he.imports.reasons[code] ?? code}<div className="small muted">{he.imports.rejectedLines}: <bdi>{lines.join(", ")}</bdi></div></div>
                <Badge kind="medium">{lines.length}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
