import itertools
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app import models as m

_n = itertools.count(1)
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def soldier(db):
    n = next(_n)
    s = m.Soldier(
        personal_number_hash=f"{n:064d}",
        personal_number_enc=b"x",
        full_name_enc=b"y",
    )
    db.add(s)
    db.flush()
    return s


def consent(db, s=None, **kw):
    s = s or soldier(db)
    c = m.Consent(
        soldier_id=s.id,
        document_ref=kw.pop("document_ref", "FORM-1"),
        signed_on=date(2026, 1, 1),
        valid_from=kw.pop("valid_from", date(2026, 1, 1)),
        valid_until=kw.pop("valid_until", date(2027, 1, 1)),
        **kw,
    )
    db.add(c)
    db.flush()
    return c


def account(db, c=None, **kw):
    c = c or consent(db)
    a = m.Account(
        soldier_id=c.soldier_id,
        consent_id=c.id,
        platform=kw.pop("platform", "instagram"),
        username=kw.pop("username", f"user{next(_n)}"),
        **kw,
    )
    db.add(a)
    db.flush()
    return a


def post(db, a=None, **kw):
    a = a or account(db)
    p = m.Post(
        account_id=a.id,
        content_hash=kw.pop("content_hash", f"c{next(_n)}"),
        collected_at=NOW,
        delete_after=kw.pop("delete_after", NOW + timedelta(days=90)),
        **kw,
    )
    db.add(p)
    db.flush()
    return p


def finding(db, p=None, **kw):
    p = p or post(db)
    f = m.Finding(
        post_id=p.id,
        kind=kw.pop("kind", "uniform"),
        score=kw.pop("score", Decimal("0.8")),
        severity=kw.pop("severity", "high"),
        reason_enc=b"r",
        evidence_hash=kw.pop("evidence_hash", f"e{next(_n)}"),
        **kw,
    )
    db.add(f)
    db.flush()
    return f


def user(db, **kw):
    u = m.User(
        email=kw.pop("email", f"u{next(_n)}@example.com"),
        password_hash="x",
        role=kw.pop("role", "reviewer"),
        **kw,
    )
    db.add(u)
    db.flush()
    return u
