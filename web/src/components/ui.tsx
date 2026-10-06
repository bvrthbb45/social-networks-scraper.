import { useEffect, useRef, type ReactNode } from "react";
import { he } from "../i18n/he";

export function Spinner({ label = he.common.loading }: { label?: string }) {
  return <p role="status" className="empty">{label}</p>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="alert error row spread">
      <span>{message}</span>
      {onRetry && <button className="btn" onClick={onRetry}>{he.common.retry}</button>}
    </div>
  );
}

export function Notice({ kind, children }: { kind: "ok" | "info" | "warn" | "error"; children: ReactNode }) {
  return <div role={kind === "error" ? "alert" : "status"} className={`alert ${kind}`}>{children}</div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Field({
  id, label, hint, children,
}: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && <span className="hint" id={`${id}-hint`}>{hint}</span>}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); previous?.focus(); };
  }, [onClose]);
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <div className="row spread" style={{ marginBlockEnd: "var(--space-4)" }}>
          <h2>{title}</h2>
          <button className="btn icon" onClick={onClose} aria-label={he.common.close}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Chevron() {
  // Points to the inline-end; `icon-flip` mirrors it in RTL so it always means "forward".
  return (
    <svg className="icon-flip" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Badge({ kind, children }: { kind?: string; children: ReactNode }) {
  return <span className={`badge ${kind ?? ""}`}>{children}</span>;
}

/** Destructive actions always go through an explicit confirmation. */
export function Confirm({
  title, message, confirmLabel, danger = false, busy = false, onConfirm, onClose,
}: { title: string; message: string; confirmLabel: string; danger?: boolean; busy?: boolean; onConfirm: () => void; onClose: () => void }) {
  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        <p>{message}</p>
        <div className="row">
          <button className={`btn ${danger ? "danger" : "primary"}`} disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
          <button className="btn" onClick={onClose}>{he.common.cancel}</button>
        </div>
      </div>
    </Modal>
  );
}
