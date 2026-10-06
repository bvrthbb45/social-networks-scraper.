# Roster and watch-list import (Loop 3)

Files are processed **in memory and never stored**; only a SHA-256 and the filename are kept for the audit trail.

## Roster workbook (first sheet, one row per account)
Generate a blank one: `python -m app.cli make-template roster roster.xlsx`

| column (Hebrew / English accepted) | rule |
|---|---|
| מספר אישי | required; stored encrypted + HMAC blind index |
| שם מלא | required; encrypted |
| יחידה | optional; encrypted |
| פלטפורמה | instagram / tiktok / facebook (or inferred from a profile URL). Anything else (e.g. WhatsApp) is **rejected** |
| חשבון | `@name`, `name` or profile URL; normalised to lower case |
| סטטוס | פתוח / סגור (or open / closed; empty = unknown) |
| אסמכתת הסכמה, תאריך חתימה, תוקף מ, תוקף עד | **required**; a row without a valid, in-force consent is rejected |

Any other column — phone numbers in particular — is **not read**; only the number of ignored columns is reported.

## Behaviour
* `dry_run=true` (the default) runs the whole import and rolls it back: you see exactly what would happen.
* Re-importing the same file changes nothing; changed status/consent dates are updated.
* An account that already belongs to another soldier is refused; a revoked consent is never revived by a re-upload.
* Rejections are returned as `reason → row numbers`. Row contents never appear in responses, logs or the audit trail.
* Limits: 5 MB, 20 000 rows, no macros, no external links, decompression-bomb check, formulas never evaluated.

## Consent lifecycle
* `POST /consents/{id}/revoke` (admin): deletes the accounts under that consent and, by cascade, everything collected from them. The consent record is kept.
* `python -m app.cli expire-consents` (run daily): same effect for consents past `valid_until`.
* `DELETE /soldiers/{id}` (admin): full erasure of the person and all derived data.

## Watch-list workbook (admin only)
Columns: מונח (required), כינויים (separated by `,` or `;`), סוג (שם קוד / אתר / יחידה / אחר), חומרה (נמוכה / בינונית / גבוהה). Terms and aliases are encrypted at rest, de-duplicated by blind index, and never written to the audit log.

## Who sees what
uploader: upload files and see import summaries only · reviewer/admin: read soldiers and accounts · admin: consent revocation, erasure, watch-list · auditor: import history and audit trail.
