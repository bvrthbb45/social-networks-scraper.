const fmt = new Intl.DateTimeFormat("he-IL", { dateStyle: "short", timeStyle: "short" });
export const formatDateTime = (iso: string | null | undefined) => (iso ? fmt.format(new Date(iso)) : "");
export const formatPercent = (score: number) => `${Math.round(score * 100)}%`;
export const formatNumber = (n: number) => new Intl.NumberFormat("he-IL").format(n);
