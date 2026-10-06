# Reviewer workflow (Loop 5)

1. A lead (finding) is created by the analysis engines. It carries a score, a Hebrew reason and the evidence that triggered it.
2. A **reviewer** opens the queue (most suspicious first; filter by status, severity, type, network) and then a finding. The page says plainly that the decision is the reviewer's.
3. Evidence images stay hidden until the reviewer asks; every image view and every finding view is written to the audit log (who, which finding, when — never the content).
4. The reviewer decides: **confirmed**, **dismissed** (with a structured reason: not relevant / ordinary word / public information / other) or **escalated**, plus an optional note (stored encrypted, never in the audit log).
5. Decisions are never overwritten: the history is kept and the latest decision is the finding's status. The structured reasons are what Loop 6 learns from.

## API added in this loop
`POST /findings/{id}/decision`, `GET /findings/{id}`, `GET /findings/{id}/media/{n}`, `GET /stats`; list filters `kind`, `platform`, `offset`; migration 0004 (`reviews.reason`).
