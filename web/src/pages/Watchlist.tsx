import { useRef, useState } from "react";
import { del, get, patch, upload } from "../api/client";
import type { Term, TermsResult } from "../api/types";
import { Badge, Confirm, Empty, ErrorBox, Notice, Spinner } from "../components/ui";
import { he } from "../i18n/he";
import { errorMessage, useAsync } from "../lib/useAsync";

export function Watchlist() {
  const { data, error, loading, reload, setData } = useAsync(() => get<Term[]>("/watchlist"), []);
  const input = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [toDelete, setToDelete] = useState<Term | null>(null);

  async function importFile(file: File | undefined) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await upload<TermsResult>("/watchlist/import", form);
      setMsg({ kind: "ok", text: he.watchlist.imported(String(r.created), String(r.updated)) });
      reload();
    } catch (e) {
      setMsg({ kind: "error", text: errorMessage(e) });
    }
    if (input.current) input.current.value = "";
  }

  async function toggle(t: Term) {
    try {
      const updated = await patch<Term>(`/watchlist/${t.id}`, { active: !t.active });
      setData((data ?? []).map((x) => (x.id === t.id ? updated : x)));
    } catch (e) { setMsg({ kind: "error", text: errorMessage(e) }); }
  }

  async function remove() {
    if (!toDelete) return;
    try { await del(`/watchlist/${toDelete.id}`); reload(); } catch (e) { setMsg({ kind: "error", text: errorMessage(e) }); }
    setToDelete(null);
  }

  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorBox message={error ?? he.common.genericError} onRetry={reload} />;
  return (
    <div className="stack">
      <div className="page-head"><h1>{he.watchlist.title}</h1></div>
      <section className="card stack">
        <h2>{he.watchlist.import}</h2>
        <p className="muted small">{he.watchlist.importHint}</p>
        <input ref={input} className="input" type="file" accept=".xlsx" aria-label={he.watchlist.import} onChange={(e) => void importFile(e.target.files?.[0])} />
      </section>
      {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
      {data.length === 0 ? <Empty title={he.watchlist.empty} /> : (
        <div className="card table-wrap"><table className="table">
          <thead><tr><th>{he.watchlist.term}</th><th>{he.watchlist.aliases}</th><th>{he.watchlist.kind}</th><th>{he.watchlist.severity}</th><th>{he.watchlist.active}</th><th /></tr></thead>
          <tbody>{data.map((t) => (
            <tr key={t.id}>
              <td data-label={he.watchlist.term} dir="auto">{t.term}</td>
              <td data-label={he.watchlist.aliases} dir="auto">{t.aliases.join(", ")}</td>
              <td data-label={he.watchlist.kind}>{he.watchlist.kinds[t.kind] ?? t.kind}</td>
              <td data-label={he.watchlist.severity}><Badge kind={t.severity}>{he.severity[t.severity]}</Badge></td>
              <td data-label={he.watchlist.active}>
                <input type="checkbox" checked={t.active} aria-label={`${he.watchlist.active}: ${t.term}`} onChange={() => void toggle(t)} />
              </td>
              <td><button className="btn danger" onClick={() => setToDelete(t)}>{he.common.delete}</button></td>
            </tr>))}</tbody>
        </table></div>
      )}
      {toDelete && <Confirm title={he.watchlist.deleteTitle} message={he.watchlist.deleteWarn} confirmLabel={he.common.delete} danger onConfirm={remove} onClose={() => setToDelete(null)} />}
    </div>
  );
}
