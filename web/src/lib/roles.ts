import type { Role } from "../api/types";

export interface NavItem { to: string; label: keyof typeof LABELS; icon: string; roles: Role[]; end?: boolean }
export const LABELS = {
  dashboard: "dashboard", findings: "findings", people: "people", imports: "imports",
  watchlist: "watchlist", learning: "learning", users: "users", audit: "audit", account: "account",
} as const;

// The server enforces every one of these; the UI only hides what a role could not use anyway.
export const NAV: NavItem[] = [
  { to: "/", label: "dashboard", icon: "◔", roles: ["reviewer", "admin", "auditor"], end: true },
  { to: "/findings", label: "findings", icon: "⚑", roles: ["reviewer", "admin"] },
  { to: "/people", label: "people", icon: "☰", roles: ["reviewer", "admin"] },
  { to: "/imports", label: "imports", icon: "⇪", roles: ["uploader", "admin", "auditor"] },
  { to: "/watchlist", label: "watchlist", icon: "◎", roles: ["admin"] },
  { to: "/learning", label: "learning", icon: "✧", roles: ["admin"] },
  { to: "/users", label: "users", icon: "☺", roles: ["admin"] },
  { to: "/audit", label: "audit", icon: "✎", roles: ["auditor", "admin"] },
  { to: "/account", label: "account", icon: "⚙", roles: ["uploader", "reviewer", "admin", "auditor"] },
];

export const navFor = (role: Role) => NAV.filter((n) => n.roles.includes(role));
export const homeFor = (role: Role) => navFor(role)[0].to;
export const can = (role: Role, path: string) => NAV.some((n) => n.to === path && n.roles.includes(role));
