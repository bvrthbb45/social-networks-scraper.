import { useEffect, useRef, type ReactNode } from "react";
import { he } from "../i18n/he";

export function Spinner({ label = he.common.loading }: { label?: string }) {
  return (
    <p role="status" className="empty">
      {label}
    </p>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="alert error row spread">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          {he.common.retry}
        </button>
      )}
    </div>
  );
}

type Tone = "ok" | "info" | "warn" | "error";

/** Inline message; errors are announced assertively, everything else politely. */
export function Notice({ kind, children }: { kind: Tone; children: ReactNode }) {
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`alert ${kind}`}>
      {children}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Badge({ kind = "", children }: { kind?: string; children: ReactNode }) {
  return <span className={`badge ${kind}`.trim()}>{children}</span>;
}

/** A labelled form control. The control must carry `id` so the label is associated with it. */
export function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && (
        <span className="hint" id={`${id}-hint`}>
          {hint}
        </span>
      )}
    </div>
  );
}

/** Modal dialog: focus moves into it, Escape and a click on the backdrop close it, focus returns after. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const closeOnEscape = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      opener?.focus();
    };
  }, [onClose]);

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={panel} className="dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <div className="row spread" style={{ marginBlockEnd: "var(--gap-4)" }}>
          <h2>{title}</h2>
          <button type="button" className="btn icon" onClick={onClose} aria-label={he.common.close}>
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Every destructive action is confirmed explicitly, with the consequence spelled out. */
export function Confirm(props: {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { title, message, confirmLabel, danger = false, busy = false, onConfirm, onClose } = props;
  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        <p>{message}</p>
        <div className="row">
          <button type="button" className={danger ? "btn danger" : "btn primary"} disabled={busy} onClick={onConfirm}>
            {confirmLabel}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            {he.common.cancel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
