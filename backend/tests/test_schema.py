from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models as m

from . import factories as f


def rejected(db, make):
    """The statement must violate a constraint. A savepoint keeps earlier work in the test intact."""
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            make()
            db.flush()


# --- consent is mandatory --------------------------------------------------- #


def test_account_without_consent_is_impossible(db):
    s = f.soldier(db)
    rejected(
        db,
        lambda: db.add(
            m.Account(
                soldier_id=s.id, consent_id=None, platform="instagram", username="a"
            )
        ),
    )


def test_account_with_unknown_consent_is_impossible(db):
    s = f.soldier(db)
    import uuid

    rejected(
        db,
        lambda: db.add(
            m.Account(
                soldier_id=s.id,
                consent_id=uuid.uuid4(),
                platform="instagram",
                username="a",
            )
        ),
    )


def test_consent_validity_must_be_ordered(db):
    s = f.soldier(db)
    rejected(
        db,
        lambda: f.consent(
            db, s, valid_from=date(2027, 1, 1), valid_until=date(2026, 1, 1)
        ),
    )


def test_consent_status_is_restricted(db):
    rejected(db, lambda: f.consent(db, status="maybe"))


# --- accounts ----------------------------------------------------------------- #


def test_whatsapp_and_other_platforms_are_not_supported(db):
    for platform in ("whatsapp", "telegram", "x"):
        rejected(db, lambda p=platform: f.account(db, platform=p))
    for platform in ("instagram", "tiktok", "facebook"):
        f.account(db, platform=platform)


def test_account_status_values(db):
    for status in ("open", "closed", "unknown", "not_found"):
        f.account(db, status=status)
    rejected(db, lambda: f.account(db, status="private"))


def test_same_username_cannot_be_registered_twice_per_platform(db):
    f.account(db, username="dana")
    rejected(db, lambda: f.account(db, username="dana"))
    f.account(db, platform="tiktok", username="dana")  # another platform is fine


# --- retention ---------------------------------------------------------------- #


def test_every_post_must_expire_after_it_was_collected(db):
    rejected(db, lambda: f.post(db, delete_after=f.NOW))
    rejected(db, lambda: f.post(db, delete_after=f.NOW - timedelta(days=1)))
    f.post(db, delete_after=f.NOW + timedelta(seconds=1))


def test_post_import_is_idempotent_per_account(db):
    a = f.account(db)
    f.post(db, a, content_hash="same")
    rejected(db, lambda: f.post(db, a, content_hash="same"))
    f.post(
        db, f.account(db), content_hash="same"
    )  # another account may hold identical content


# --- findings and reviews ----------------------------------------------------- #


@pytest.mark.parametrize("score", [Decimal("-0.001"), Decimal("1.001"), Decimal("2")])
def test_score_must_be_between_zero_and_one(db, score):
    rejected(db, lambda: f.finding(db, score=score))


@pytest.mark.parametrize("score", [Decimal("0"), Decimal("0.5"), Decimal("1")])
def test_valid_scores(db, score):
    f.finding(db, score=score)


def test_finding_enumerations_are_restricted(db):
    rejected(db, lambda: f.finding(db, kind="mind_reading"))
    rejected(db, lambda: f.finding(db, severity="critical"))
    rejected(db, lambda: f.finding(db, status="auto_punished"))
    for kind in m.FINDING_KINDS:
        f.finding(db, kind=kind)


def test_analysis_is_idempotent(db):
    p = f.post(db)
    f.finding(db, p, kind="uniform", evidence_hash="E")
    rejected(db, lambda: f.finding(db, p, kind="uniform", evidence_hash="E"))
    f.finding(db, p, kind="uniform", evidence_hash="E2")
    f.finding(db, p, kind="equipment", evidence_hash="E")


def test_review_decisions_are_restricted(db):
    fi = f.finding(db)
    u = f.user(db)
    for d in m.DECISIONS:
        db.add(m.Review(finding_id=fi.id, reviewer_id=u.id, decision=d))
    db.flush()
    rejected(
        db,
        lambda: db.add(m.Review(finding_id=fi.id, reviewer_id=u.id, decision="punish")),
    )


# --- operators ----------------------------------------------------------------- #


def test_only_the_four_roles_exist(db):
    for role in m.ROLES:
        f.user(db, role=role)
    rejected(db, lambda: f.user(db, role="superuser"))


def test_email_is_unique(db):
    f.user(db, email="a@example.com")
    rejected(db, lambda: f.user(db, email="a@example.com"))


def test_watchlist_terms_are_unique_by_blind_index(db):
    db.add(m.WatchlistTerm(term_hash="h1", term_enc=b"x"))
    db.flush()
    rejected(db, lambda: db.add(m.WatchlistTerm(term_hash="h1", term_enc=b"y")))
    rejected(
        db,
        lambda: db.add(
            m.WatchlistTerm(term_hash="h2", term_enc=b"y", severity="extreme")
        ),
    )


def test_soldier_personal_number_blind_index_is_unique(db):
    f.soldier(db)
    s = m.Soldier(
        personal_number_hash=db.scalar(select(m.Soldier.personal_number_hash)),
        personal_number_enc=b"x",
        full_name_enc=b"y",
    )
    rejected(db, lambda: db.add(s))


# --- withdrawal of consent removes everything downstream ------------------------ #


def _chain(db):
    c = f.consent(db)
    a = f.account(db, c)
    p = f.post(db, a)
    fi = f.finding(db, p)
    db.add(m.Review(finding_id=fi.id, decision="dismissed"))
    db.flush()
    return c, a, p, fi


def _counts(db):
    return [
        db.query(t).count() for t in (m.Consent, m.Account, m.Post, m.Finding, m.Review)
    ]


def test_deleting_a_consent_deletes_accounts_posts_findings_and_reviews(db):
    c, *_ = _chain(db)
    assert _counts(db) == [1, 1, 1, 1, 1]
    db.delete(c)
    db.commit()
    assert _counts(db) == [0, 0, 0, 0, 0]


def test_deleting_a_soldier_deletes_everything_about_them(db):
    c, *_ = _chain(db)
    db.delete(db.get(m.Soldier, c.soldier_id))
    db.commit()
    assert _counts(db) == [0, 0, 0, 0, 0]
    assert db.query(m.Soldier).count() == 0


def test_deleting_an_account_leaves_the_consent(db):
    c, a, *_ = _chain(db)
    db.delete(a)
    db.commit()
    assert _counts(db) == [1, 0, 0, 0, 0]
