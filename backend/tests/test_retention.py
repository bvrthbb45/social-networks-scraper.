import io
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import media
from app import models as m
from app import retention
from app.config import settings
from app.security import crypto
from tests import factories as f
from tests.test_auth_api import api, db, env  # noqa: F401
from tests.test_learning import (
    World,
    keys,
)  # noqa: F401  (key setup + reviewed-finding builder)

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def media_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path / "media"))
    return tmp_path / "media"


def post_with(db, account, ref=None, *, due=False, text="טקסט"):
    p = f.post(
        db,
        account,
        delete_after=NOW - timedelta(minutes=1) if due else NOW + timedelta(days=30),
    )
    p.text_enc = crypto.encrypt_text(text, f"posts.text:{p.id}")
    if ref:
        p.media = [{"kind": "image", "ref": ref, "gps": False}]
    return p


def finding_for(db, post, *, reviewed=False):
    fid = uuid.uuid4()
    fnd = m.Finding(
        id=fid,
        post_id=post.id,
        kind="codename",
        score=0.5,
        severity="medium",
        reason_enc=crypto.encrypt_text("r", f"findings.reason:{fid}"),
        evidence_hash=uuid.uuid4().hex * 2,
    )
    db.add(fnd)
    db.flush()
    if reviewed:
        db.add(m.Review(finding_id=fid, decision="dismissed", decided_at=NOW))
    db.flush()
    return fnd


def open_account(db):
    c = f.consent(
        db,
        valid_from=date.today() - timedelta(days=5),
        valid_until=date.today() + timedelta(days=100),
    )
    return f.account(db, c, status="open")


def test_expired_posts_are_deleted_with_their_findings_and_reviews(db):
    a = open_account(db)
    old, new = post_with(db, a, due=True), post_with(db, a)
    fo, fn = finding_for(db, old, reviewed=True), finding_for(db, new)
    db.commit()
    old_id, fo_id, new_id, fn_id = old.id, fo.id, new.id, fn.id
    counts = retention.purge_expired_posts(db)
    db.commit()
    assert counts == {
        "posts": 1,
        "findings": 1,
        "reviewed_findings": 1,
        "media_files": 0,
    }
    db.expire_all()
    assert db.get(m.Post, old_id) is None and db.get(m.Finding, fo_id) is None
    assert (
        db.scalar(select(m.Review)) is None
    )  # reviews of the purged finding went with it
    assert db.get(m.Post, new_id) and db.get(m.Finding, fn_id)  # live data untouched


def test_nothing_due_means_nothing_happens_and_rerunning_is_harmless(db):
    a = open_account(db)
    post_with(db, a)
    db.commit()
    assert retention.purge_expired_posts(db)["posts"] == 0
    assert retention.purge_expired_posts(db)["posts"] == 0


def test_media_files_go_with_the_post_unless_another_post_still_uses_them(
    db, media_dir
):
    a = open_account(db)
    solo = media.save(b"only-used-by-expired-post")
    shared = media.save(b"shared-picture")
    post_with(db, a, solo, due=True)
    post_with(db, a, shared, due=True)
    post_with(db, a, shared)  # a live post still shows the shared picture
    db.commit()
    counts = retention.purge_expired_posts(db)
    db.commit()
    assert counts["media_files"] == 1
    assert not (media_dir / solo[:2] / f"{solo}.bin").exists()
    assert (media_dir / shared[:2] / f"{shared}.bin").exists()  # still needed
    assert media.load(shared) == b"shared-picture"


def test_orphan_sweep_removes_only_old_unreferenced_files(db, media_dir):
    a = open_account(db)
    kept = media.save(b"referenced")
    post_with(db, a, kept)
    old_orphan, fresh_orphan = media.save(b"orphan-old"), media.save(b"orphan-fresh")
    long_ago = time.time() - 3 * 24 * 3600
    path = media_dir / old_orphan[:2] / f"{old_orphan}.bin"
    os.utime(path, (long_ago, long_ago))
    os.utime(media_dir / kept[:2] / f"{kept}.bin", (long_ago, long_ago))
    db.commit()
    assert retention.sweep_orphan_media(db) == 1
    assert not path.exists()
    assert (
        media_dir / fresh_orphan[:2] / f"{fresh_orphan}.bin"
    ).exists()  # may belong to an import in flight
    assert (
        media_dir / kept[:2] / f"{kept}.bin"
    ).exists()  # referenced: even though it is old


def test_session_artefacts_are_cleaned_only_when_long_dead(db):
    u = m.User(email="x@example.org", role="admin", password_hash="!")
    db.add(u)
    db.flush()
    live, dead_old, dead_recent = (
        m.Device(user_id=u.id, kind="web", name=n)
        for n in ("live", "dead-old", "dead-recent")
    )
    dead_old.revoked_at = NOW - timedelta(days=200)
    dead_recent.revoked_at = NOW - timedelta(days=5)
    db.add_all([live, dead_old, dead_recent])
    db.flush()
    db.add_all(
        [
            m.RefreshToken(
                device_id=live.id,
                token_hash="a" * 64,
                expires_at=NOW + timedelta(days=1),
            ),
            m.RefreshToken(
                device_id=live.id,
                token_hash="b" * 64,
                expires_at=NOW - timedelta(days=100),
            ),
            m.RefreshToken(
                device_id=live.id,
                token_hash="c" * 64,
                expires_at=NOW + timedelta(days=1),
                revoked_at=NOW - timedelta(days=60),
            ),
            m.RefreshToken(
                device_id=live.id,
                token_hash="d" * 64,
                expires_at=NOW + timedelta(days=1),
                revoked_at=NOW - timedelta(days=1),
            ),
            m.Invite(
                user_id=u.id, token_hash="e" * 64, expires_at=NOW - timedelta(days=90)
            ),
            m.Invite(
                user_id=u.id, token_hash="f" * 64, expires_at=NOW + timedelta(days=1)
            ),
        ]
    )
    db.commit()
    counts = retention.cleanup_sessions(db)
    db.commit()
    assert counts == {"refresh_tokens": 2, "invites": 1, "devices": 1}
    assert {d.name for d in db.scalars(select(m.Device)).all()} == {
        "live",
        "dead-recent",
    }
    assert {t.token_hash[0] for t in db.scalars(select(m.RefreshToken)).all()} == {
        "a",
        "d",
    }  # recent revocation kept for reuse detection
    assert len(db.scalars(select(m.Invite)).all()) == 1


def test_routine_retention_does_not_retire_models_but_staleness_policy_can(
    db, monkeypatch
):
    from app.learning import service

    w = World(db)
    w.labelled_set()
    mod = service.train_candidate(db, None)
    for i in range(2):
        u = m.User(email=f"adm{i}@example.org", role="admin", password_hash="!")
        db.add(u)
        db.flush()
        service.approve(db, mod, u.id)
    service.activate(db, mod)
    old = post_with(db, w.account, due=True)
    finding_for(db, old, reviewed=True)
    db.commit()
    assert retention.purge_expired_posts(db)["reviewed_findings"] == 1
    db.refresh(mod)
    assert mod.status == "active"  # routine expiry alone never switches the model off
    assert retention.retire_stale_models(db) == 0  # policy is off by default
    monkeypatch.setattr(settings, "learning_max_model_age_days", 30)
    assert retention.retire_stale_models(db, NOW + timedelta(days=10)) == 0
    assert retention.retire_stale_models(db, NOW + timedelta(days=45)) == 1
    db.refresh(mod)
    assert mod.status == "retired" and mod.note == "stale"


def test_daily_run_does_everything_and_audits_counts_only(db, media_dir):
    a = open_account(db)
    ref = media.save(b"expired-image")
    post_with(db, a, ref, due=True, text="סודי מאוד")
    c2 = f.consent(
        db,
        valid_from=date.today() - timedelta(days=400),
        valid_until=date.today() - timedelta(days=1),
    )
    f.account(db, c2, status="open", username="lapsed")
    db.commit()
    out = retention.run_daily(db)
    assert (
        out["purged"]["posts"] == 1
        and out["purged"]["media_files"] == 1
        and out["consents_expired"] == 1
    )
    log = db.scalars(
        select(m.AuditLog).where(m.AuditLog.action == "maintenance.daily")
    ).one()
    assert log.user_id is None and log.details["purged.posts"] == 1
    assert "סודי" not in str(log.details)
    assert not (media_dir / ref[:2] / f"{ref}.bin").exists()
    assert (
        db.scalar(select(m.Account).where(m.Account.username == "lapsed")) is None
    )  # expired consent => no monitoring


def test_retention_is_enforced_on_postgres_with_real_cascades(pg_url, monkeypatch):
    """Same purge against the real schema (foreign keys, cascades, JSONB media column)."""
    import sqlalchemy as sa
    from sqlalchemy.orm import Session
    from tests.test_postgres import alembic

    assert (
        alembic(pg_url, "downgrade", "base").returncode == 0
        and alembic(pg_url, "upgrade", "head").returncode == 0
    )
    eng = sa.create_engine(pg_url)
    with Session(eng) as db:
        s = m.Soldier(
            personal_number_hash="1" * 64, personal_number_enc=b"x", full_name_enc=b"y"
        )
        db.add(s)
        db.flush()
        c = m.Consent(
            soldier_id=s.id,
            document_ref="F",
            signed_on=date.today(),
            valid_from=date.today(),
            valid_until=date.today() + timedelta(days=9),
        )
        db.add(c)
        db.flush()
        a = m.Account(
            soldier_id=s.id,
            consent_id=c.id,
            platform="instagram",
            username="pgtest",
            status="open",
        )
        db.add(a)
        db.flush()
        db.add_all(
            [
                m.Post(
                    account_id=a.id,
                    content_hash="old",
                    collected_at=NOW - timedelta(days=100),
                    delete_after=NOW - timedelta(days=10),
                ),
                m.Post(
                    account_id=a.id,
                    content_hash="new",
                    collected_at=NOW,
                    delete_after=NOW + timedelta(days=80),
                ),
            ]
        )
        db.commit()
        old_id = db.scalar(sa.select(m.Post.id).where(m.Post.content_hash == "old"))
        fnd = m.Finding(
            post_id=old_id,
            kind="codename",
            score=0.5,
            severity="low",
            reason_enc=b"r",
            evidence_hash="e" * 64,
        )
        db.add(fnd)
        db.commit()
        assert retention.purge_expired_posts(db) == {
            "posts": 1,
            "findings": 1,
            "reviewed_findings": 0,
            "media_files": 0,
        }
        db.commit()
        assert [p.content_hash for p in db.scalars(sa.select(m.Post)).all()] == ["new"]
        assert db.scalar(sa.select(sa.func.count()).select_from(m.Finding)) == 0
    eng.dispose()


_ = io
