export type Role = "uploader" | "reviewer" | "admin" | "auditor";
export type Severity = "low" | "medium" | "high";
export type FindingStatus = "new" | "in_review" | "confirmed" | "dismissed" | "escalated";
export type Decision = "confirmed" | "dismissed" | "escalated";
export type DismissReason = "not_relevant" | "common_word" | "public_info" | "other";

export interface Session { access_token: string; expires_in: number; device_id: string; recovery_codes?: string[] | null; refresh_token?: string | null }
export interface StepToken { status: "mfa_required" | "2fa_setup_required"; token: string }
export interface TotpSetup { secret: string; otpauth_uri: string }

export interface User {
  id: string; email: string; display_name: string; role: Role; is_active: boolean;
  totp_enabled: boolean; last_login_at: string | null;
}
export interface Invite { user_id: string; token: string; expires_at: string; purpose: "invite" | "reset" }
export interface Device { id: string; kind: "web" | "android"; name: string; created_at: string; last_seen_at: string | null; revoked_at: string | null; current: boolean }

export interface FindingRow {
  id: string; kind: string; severity: Severity; score: number; adjusted_score: number | null; lane: "normal" | "low";
  status: FindingStatus; reason: string;
  source: string | null; snippet: string | null; platform: string; username: string;
  post_url: string | null; posted_at: string | null; created_at: string;
}
export interface HistoryItem { decision: Decision; reason: DismissReason | null; note: string | null; reviewer: string | null; decided_at: string }
export interface FindingDetail extends FindingRow {
  learning: string[]; engine_version: string; post_text: string; media: { index: number; kind: string }[]; history: HistoryItem[];
}
export interface Stats {
  findings_by_status: Record<string, number>; open_by_severity: Record<string, number>;
  open_by_kind: Record<string, number>; accounts_by_status: Record<string, number>; last_import_at: string | null;
}

export interface ImportSummary {
  dry_run: boolean; import_id: string | null; duplicate_file: boolean; rows_total: number;
  soldiers_created: number; accounts_created: number; accounts_updated: number; unchanged: number;
  rejected: Record<string, number[]>; unused_columns: number; phone_columns_ignored: number;
}
export interface ImportRow { id: string; filename: string; status: string; rows_total: number; rows_accepted: number; rows_rejected: number; uploaded_at: string }
export interface TermsResult { created: number; updated: number; rejected: Record<string, number[]> }

export interface SoldierRow { id: string; full_name: string; unit: string | null; accounts: number; consents: { id: string; ref: string; status: string; valid_until: string }[] }
export interface Term { id: string; term: string; aliases: string[]; kind: string; severity: Severity; active: boolean }
export interface AuditRow { id: number; user_id: string | null; action: string; object_type: string | null; object_id: string | null; ip: string | null; details: Record<string, unknown> | null; created_at: string }

export interface LearningModel {
  id: string; version: number; status: "candidate" | "shadow" | "active" | "retired" | "rejected"; trained_on: number;
  metrics: { baseline_auc: number | null; model_auc: number | null; n_labels: number; blockers: string[] } | null;
  note: string | null; approvals: number; created_at: string; activated_at: string | null;
}
export interface LearningStatus {
  labels: number; positives: number; min_labels: number; required_approvals: number; golden_cases: number;
  active: LearningModel | null; undecided_open: number;
}
export interface TermStat {
  id: string; term: string; severity: Severity; n: number; confirmed: number; precision: number;
  advice: "mostly_false_alarms" | "effective" | null; dismiss_reasons: Record<string, number>;
}
export interface TermSuggestion { token: string; confirmed_posts: number; accounts: number; dismissed_posts: number }
export interface GoldenCase { id: string; text: string; kind: string }

export interface ReportSummary {
  days: number; findings_created: number; created_by_kind: Record<string, number>; created_by_severity: Record<string, number>;
  decisions: Record<string, number>; dismissal_reasons: Record<string, number>;
  false_alarm_by_kind: Record<string, { decided: number; dismissed: number; rate: number }>;
  median_hours_to_decision: number | null; backlog: number; oldest_open_hours: number | null;
  accounts_by_status: Record<string, number>; imports: { files: number; rows: number; rejected_rows: number };
  security_events: Record<string, number>; learning: { version: number; age_days: number } | null;
}
export interface RetentionStatus {
  retention_days: number; posts_total: number; overdue: number; due_within_7_days: number; oldest_post_days: number | null;
  last_run: { at: string; counts: Record<string, number> } | null;
}
export interface ExpiringConsent { consent_id: string; soldier: string; ref: string; valid_until: string; days_left: number; accounts: number }
