"""Apply a parsed roster to the database. One transaction; a dry run rolls it back."""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, Consent, Import, Soldier, WatchlistTerm
from ..security import crypto
from .excel import Parsed, Term

PN = "personal_number"


def soldier_hash(personal_number: str) -> str:
    return crypto.blind_index(personal_number, PN)


def soldier_ctx(sid: uuid.UUID, column: str) -> str:
    return f"soldiers.{column}:{sid}"


@dataclass
class Result:
    soldiers_created: int = 0
    accounts_created: int = 0
    accounts_updated: int = 0
    unchanged: int = 0
    rejected: dict[str, list[int]] = field(default_factory=dict)

    def reject(self, code: str, line: int) -> None:
        self.rejected.setdefault(code, []).append(line)


def apply_roster(
    db: Session, parsed: Parsed, filename: str, data: bytes, actor: uuid.UUID
) -> tuple[Import, Result]:
    now = datetime.now(timezone.utc)
    res = Result(rejected={k: list(v) for k, v in parsed.rejected.items()})
    imp = Import(
        uploaded_by=actor,
        filename=_safe_name(filename),
        sha256=hashlib.sha256(data).hexdigest(),
        status="processing",
    )
    db.add(imp)
    db.flush()

    soldiers: dict[str, Soldier] = {}
    for row in parsed.rows:
        h = soldier_hash(row.personal_number)
        soldier = soldiers.get(h) or db.scalar(
            select(Soldier).where(Soldier.personal_number_hash == h)
        )
        if soldier is None:
            sid = uuid.uuid4()
            soldier = Soldier(
                id=sid,
                personal_number_hash=h,
                personal_number_enc=crypto.encrypt_text(
                    row.personal_number, soldier_ctx(sid, "personal_number")
                ),
                full_name_enc=crypto.encrypt_text(
                    row.full_name, soldier_ctx(sid, "full_name")
                ),
                unit_enc=(
                    crypto.encrypt_text(row.unit, soldier_ctx(sid, "unit"))
                    if row.unit
                    else None
                ),
            )
            db.add(soldier)
            db.flush()
            res.soldiers_created += 1
        soldiers[h] = soldier

        consents = db.scalars(
            select(Consent).where(
                Consent.soldier_id == soldier.id,
                Consent.document_ref == row.consent_ref,
            )
        ).all()
        if any(c.status == "revoked" for c in consents):
            res.reject(
                "consent_revoked", row.line
            )  # a revoked consent is never silently revived
            continue
        consent = next((c for c in consents if c.status == "active"), None)
        if consent is None:
            consent = Consent(
                soldier_id=soldier.id,
                document_ref=row.consent_ref,
                signed_on=row.consent_signed,
                valid_from=row.consent_from,
                valid_until=row.consent_until,
                recorded_by=actor,
            )
            db.add(consent)
            db.flush()
        else:
            consent.valid_from, consent.valid_until = (
                row.consent_from,
                row.consent_until,
            )

        acct = db.scalar(
            select(Account).where(
                Account.platform == row.platform, Account.username == row.username
            )
        )
        if acct is not None and acct.soldier_id != soldier.id:
            res.reject("account_belongs_to_other_soldier", row.line)
            continue
        if acct is None:
            db.add(
                Account(
                    soldier_id=soldier.id,
                    consent_id=consent.id,
                    platform=row.platform,
                    username=row.username,
                    status=row.status,
                    status_checked_at=now,
                    source_import_id=imp.id,
                )
            )
            res.accounts_created += 1
        elif acct.status != row.status or acct.consent_id != consent.id:
            acct.status, acct.consent_id = row.status, consent.id
            acct.status_checked_at, acct.source_import_id = now, imp.id
            res.accounts_updated += 1
        else:
            res.unchanged += 1
        db.flush()

    rejected_total = sum(len(v) for v in res.rejected.values())
    imp.rows_total = parsed.total
    imp.rows_rejected = rejected_total
    imp.rows_accepted = parsed.total - rejected_total
    imp.reject_reasons = {k: len(v) for k, v in res.rejected.items()}
    imp.status = "done"
    return imp, res


def _safe_name(name: str) -> str:
    base = (name or "upload.xlsx").replace("\\", "/").rsplit("/", 1)[-1]
    return (
        "".join(ch for ch in base if ch.isprintable() and ch not in '<>"|?*')[:200]
        or "upload.xlsx"
    )


def apply_terms(db: Session, terms: list[Term], actor: uuid.UUID) -> dict[str, int]:
    created = updated = 0
    for t in terms:
        h = crypto.blind_index(t.term, "watchlist_term")
        row = db.scalar(select(WatchlistTerm).where(WatchlistTerm.term_hash == h))
        if row is None:
            tid = uuid.uuid4()
            row = WatchlistTerm(id=tid, term_hash=h, term_enc=b"", created_by=actor)
            db.add(row)
            created += 1
        else:
            updated += 1
        ctx = lambda col: f"watchlist_terms.{col}:{row.id}"  # noqa: E731
        row.term_enc = crypto.encrypt_text(t.term, ctx("term"))
        row.aliases_enc = (
            crypto.encrypt_json(t.aliases, ctx("aliases")) if t.aliases else None
        )
        row.kind, row.severity, row.active = t.kind, t.severity, True
        db.flush()
    return {"created": created, "updated": updated}
