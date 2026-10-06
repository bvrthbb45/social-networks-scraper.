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
  id: string; kind: string; severity: Severity; score: number; status: FindingStatus; reason: string;
  source: string | null; snippet: string | null; platform: string; username: string;
  post_url: string | null; posted_at: string | null; created_at: string;
}
export interface HistoryItem { decision: Decision; reason: DismissReason | null; note: string | null; reviewer: string | null; decided_at: string }
export interface FindingDetail extends FindingRow {
  engine_version: string; post_text: string; media: { index: number; kind: string }[]; history: HistoryItem[];
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
