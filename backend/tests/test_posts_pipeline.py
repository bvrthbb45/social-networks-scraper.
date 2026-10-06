import base64
import io
from datetime import date, datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import select

from app import media
from app import models as m
from app.analysis import pipeline
from app.analysis.text import TermSpec
from app.config import settings
from tests import factories as f
from tests.test_auth_api import api, auth, db, enrol, env, make_user  # noqa: F401
from tests.test_import_api import session_for
from tests.xlsx_helpers import terms_workbook


@pytest.fixture(autouse=True)
def media_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path / "media"))
    return tmp_path / "media"


def b64(im: Image.Image, fmt="PNG", **kw) -> str:
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return base64.b64encode(buf.getvalue()).decode()


def olive_person():
    im = Image.new("RGB", (200, 300), (120, 120, 120))
    im.paste((85, 107, 47), (80, 60, 140, 200))
    return im


def gps_jpeg():
    exif = Image.Exif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (32.0, 5.0, 8.0), "E", (34.0, 46.0, 54.0)
    return b64(Image.new("RGB", (64, 64), (30, 30, 30)), "JPEG", exif=exif)


def add_terms(api, admin):
    data = terms_workbook(
        [("נשר שחור", "", "שם קוד", "גבוהה"), ("בסיס צפוני", "", "אתר", "גבוהה")]
    )
    assert (
        api.post(
            "/watchlist/import", headers=admin, files={"file": ("t.xlsx", data)}
        ).status_code
        == 200
    )


def push(api, h, items, username="soldier_x", platform="instagram"):
    return api.post(
        "/posts/import",
        headers=h,
        json={"platform": platform, "username": username, "items": items},
    )


def test_text_post_produces_findings_reviewer_can_read(api, db):
    seed_open(db)
    ad, up, rv = (session_for(api, db, r) for r in ("admin", "uploader", "reviewer"))
    add_terms(api, ad)
    r = push(
        api, up, [{"text": "אנחנו כרגע בבסיס צפוני. מסמך סודי", "url": "https://x/1"}]
    )
    assert (
        r.status_code == 200
        and r.json()["created"] == 1
        and r.json()["findings_created"] >= 2
    )
    rows = api.get("/findings", headers=rv).json()
    kinds = {x["kind"] for x in rows}
    assert {"location", "text_pattern"} <= kinds
    top = max(rows, key=lambda x: x["score"])
    assert (
        top["username"] == "soldier_x"
        and top["platform"] == "instagram"
        and top["reason"]
        and top["post_url"] == "https://x/1"
    )
    # at rest: text and finding details are ciphertext
    raw = db.scalar(select(m.Post)).text_enc
    assert "בסיס".encode() not in raw
    assert all(
        "בסיס".encode() not in fnd.reason_enc
        for fnd in db.scalars(select(m.Finding)).all()
    )
    assert (
        str([a.details for a in db.scalars(select(m.AuditLog)).all()]).count("בסיס")
        == 0
    )


def seed_open(db):
    c = f.consent(
        db,
        valid_from=date.today() - timedelta(days=5),
        valid_until=date.today() + timedelta(days=100),
    )
    a = f.account(db, c, status="open", username="soldier_x")
    db.commit()
    return a, c


@pytest.mark.parametrize("status_", ["closed", "unknown", "not_found"])
def test_non_open_accounts_collect_nothing(api, db, status_):
    a, _ = seed_open(db)
    a.status = status_
    db.commit()
    up = session_for(api, db, "uploader")
    r = push(api, up, [{"text": "hello"}])
    assert r.status_code == 409 and r.json()["detail"] == "account_not_open"
    assert db.scalar(select(m.Post)) is None


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda c: setattr(c, "status", "revoked"), "no_active_consent"),
        (
            lambda c: setattr(c, "valid_until", date.today() - timedelta(days=1)),
            "consent_not_in_force",
        ),
        (
            lambda c: setattr(c, "valid_from", date.today() + timedelta(days=1)),
            "consent_not_in_force",
        ),
    ],
)
def test_consent_must_be_active_and_in_date(api, db, mutate, code):
    a, c = seed_open(db)
    mutate(c)
    db.commit()
    up = session_for(api, db, "uploader")
    r = push(api, up, [{"text": "hello"}])
    assert (
        r.status_code == 409
        and r.json()["detail"] == code
        and db.scalar(select(m.Post)) is None
    )
    assert db.scalar(select(m.AuditLog).where(m.AuditLog.action == "posts.refused"))


def test_unknown_account_and_unsupported_platform(api, db):
    seed_open(db)
    up = session_for(api, db, "uploader")
    assert (
        push(api, up, [{"text": "x"}], username="nobody").json()["detail"]
        == "unknown_account"
    )
    assert push(api, up, [{"text": "x"}], platform="whatsapp").status_code == 422


def test_pipeline_rechecks_eligibility_even_for_existing_posts(db):
    c = f.consent(
        db,
        valid_from=date.today() - timedelta(days=5),
        valid_until=date.today() + timedelta(days=100),
    )
    a = f.account(db, c, status="closed")
    p = f.post(db, a, delete_after=datetime.now(timezone.utc) + timedelta(days=5))
    from app.security import crypto

    p.text_enc = crypto.encrypt_text("מסמך סודי ביותר", f"posts.text:{p.id}")
    db.commit()
    assert (
        pipeline.analyze_post(db, p, []) == 0 and db.scalar(select(m.Finding)) is None
    )
    a.status = "open"
    c.status = "revoked"
    assert pipeline.analyze_post(db, p, []) == 0
    c.status, a.status = "active", "open"
    p.delete_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert pipeline.analyze_post(db, p, []) == 0  # expired content is not analysed
    p.delete_after = datetime.now(timezone.utc) + timedelta(days=1)
    assert pipeline.analyze_post(db, p, []) >= 1


def test_idempotent_duplicates_and_reanalysis(api, db):
    seed_open(db)
    up = session_for(api, db, "uploader")
    first = push(api, up, [{"text": "מסמך סודי"}]).json()
    again = push(api, up, [{"text": "מסמך סודי"}]).json()
    assert first["created"] == 1 and again["created"] == 0 and again["duplicates"] == 1
    n = len(db.scalars(select(m.Finding)).all())
    post = db.scalar(select(m.Post))
    assert pipeline.analyze_post(db, post, []) == 0  # same evidence -> no new rows
    assert len(db.scalars(select(m.Finding)).all()) == n


def test_retention_date_is_set_on_intake(api, db, monkeypatch):
    monkeypatch.setattr(settings, "retention_days", 30)
    seed_open(db)
    up = session_for(api, db, "uploader")
    push(api, up, [{"text": "שלום"}])
    p = db.scalar(select(m.Post))
    delta = p.delete_after.replace(tzinfo=timezone.utc) - p.collected_at.replace(
        tzinfo=timezone.utc
    )
    assert timedelta(days=29, hours=23) < delta < timedelta(days=30, hours=1)


def test_images_are_stored_encrypted_stripped_and_analysed(api, db, media_dir):
    seed_open(db)
    up = session_for(api, db, "uploader")
    rv = session_for(api, db, "reviewer")
    r = push(api, up, [{"text": "תמונה", "images": [b64(olive_person()), gps_jpeg()]}])
    assert r.json()["created"] == 1
    kinds = {x["kind"]: x for x in api.get("/findings", headers=rv).json()}
    assert (
        kinds["uniform"]["severity"] == "low" and kinds["uniform"]["source"] == "image"
    )
    assert (
        kinds["location"]["source"] == "exif"
        and kinds["location"]["severity"] == "high"
    )
    files = list(media_dir.rglob("*.bin"))
    assert len(files) == 2
    for fl in files:
        blob = fl.read_bytes()
        assert (
            not blob.startswith((b"\xff\xd8", b"\x89PNG")) and b"JFIF" not in blob
        )  # ciphertext only
        assert oct(fl.stat().st_mode & 0o777) == "0o600"
    ref = db.scalar(select(m.Post)).media[1]["ref"]
    stored = Image.open(io.BytesIO(media.load(ref)))
    assert not stored.getexif().get_ifd(0x8825)  # GPS removed from what we keep
    with pytest.raises(Exception):
        media.load("../../etc/passwd")


def test_bad_content_is_rejected_per_item(api, db):
    seed_open(db)
    up = session_for(api, db, "uploader")
    items = [
        {"text": "ok"},
        {"images": ["!!notbase64!!"]},
        {"images": [base64.b64encode(b"not an image").decode()]},
        {"images": [b64(Image.new("RGB", (8, 8)))] * 6},
        {"text": "   "},
    ]
    r = push(api, up, items).json()
    assert r["created"] == 1 and r["rejected"] == {
        "bad_image_encoding": 1,
        "image_unreadable": 1,
        "too_many_images": 1,
        "empty_post": 1,
    }


def test_batch_and_field_limits(api, db):
    seed_open(db)
    up = session_for(api, db, "uploader")
    assert push(api, up, [{"text": "x"}] * 21).status_code == 422
    assert push(api, up, []).status_code == 422
    assert push(api, up, [{"text": "x" * 20_001}]).status_code == 422
    assert (
        api.post(
            "/posts/import",
            headers=up,
            json={
                "platform": "instagram",
                "username": "soldier_x",
                "items": [{"text": "x", "evil": 1}],
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "role,imp,read",
    [
        ("uploader", True, False),
        ("admin", True, True),
        ("reviewer", False, True),
        ("auditor", False, False),
    ],
)
def test_roles(api, db, role, imp, read):
    seed_open(db)
    h = session_for(api, db, role)
    assert (push(api, h, [{"text": "מסמך סודי"}]).status_code == 200) == imp
    assert (api.get("/findings", headers=h).status_code == 200) == read


def test_analyze_pending_picks_up_unanalysed_and_skips_ineligible(db):
    from app.security import crypto

    c = f.consent(
        db,
        valid_from=date.today() - timedelta(days=5),
        valid_until=date.today() + timedelta(days=100),
    )
    ok = f.account(db, c, status="open")
    closed = f.account(db, c, status="closed")
    for a in (ok, closed):
        p = f.post(db, a, delete_after=datetime.now(timezone.utc) + timedelta(days=5))
        p.text_enc = crypto.encrypt_text("מסמך סודי", f"posts.text:{p.id}")
    db.commit()
    assert pipeline.analyze_pending(db) >= 1
    posts = {p.account_id: p for p in db.scalars(select(m.Post)).all()}
    assert posts[ok.id].analyzed_version == pipeline.ENGINE_VERSION
    assert posts[closed.id].analyzed_version is None
    assert {x.post_id for x in db.scalars(select(m.Finding)).all()} == {posts[ok.id].id}


def test_inactive_watchlist_terms_are_ignored(api, db):
    seed_open(db)
    ad, up = session_for(api, db, "admin"), session_for(api, db, "uploader")
    add_terms(api, ad)
    for t in api.get("/watchlist", headers=ad).json():
        api.patch(f"/watchlist/{t['id']}", headers=ad, json={"active": False})
    r = push(api, up, [{"text": "בבסיס צפוני"}]).json()
    assert r["findings_created"] == 0


_ = (TermSpec, enrol, make_user, auth)
