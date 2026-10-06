import pytest
from sqlalchemy import select

from app import models as m
from tests.test_auth_api import api, auth, db, enrol, env, make_user  # noqa: F401
from tests.test_import_api import session_for
from tests.test_posts_pipeline import (
    add_terms,
    b64,
    gps_jpeg,
    media_dir,
    olive_person,
    push,
    seed_open,
)  # noqa: F401


def seeded(api, db):
    seed_open(db)
    ad, up, rv = (session_for(api, db, r) for r in ("admin", "uploader", "reviewer"))
    add_terms(api, ad)
    r = push(
        api,
        up,
        [
            {
                "text": "אנחנו כרגע בבסיס צפוני. מסמך סודי",
                "images": [b64(olive_person()), gps_jpeg()],
                "url": "https://x/1",
            }
        ],
    )
    assert r.json()["findings_created"] >= 3
    return ad, up, rv


def first(api, h, **q):
    return api.get("/findings", headers=h, params=q).json()


def test_detail_shows_text_media_and_empty_history(api, db):
    _, _, rv = seeded(api, db)
    fid = first(api, rv)[0]["id"]
    d = api.get(f"/findings/{fid}", headers=rv).json()
    assert (
        "בסיס צפוני" in d["post_text"]
        and [x["index"] for x in d["media"]] == [0, 1]
        and d["history"] == []
    )
    assert d["username"] == "soldier_x" and d["reason"]
    assert db.scalar(select(m.AuditLog).where(m.AuditLog.action == "finding.viewed"))


def test_media_is_served_decoded_private_and_audited(api, db):
    _, _, rv = seeded(api, db)
    fid = first(api, rv)[0]["id"]
    r = api.get(f"/findings/{fid}/media/0", headers=rv)
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
    assert (
        "no-store" in r.headers["cache-control"]
        and r.headers["x-content-type-options"] == "nosniff"
    )
    assert r.headers["content-type"] == "image/jpeg"
    assert api.get(f"/findings/{fid}/media/9", headers=rv).status_code == 404
    assert api.get(f"/findings/{fid}/media/-1", headers=rv).status_code == 404
    log = db.scalar(select(m.AuditLog).where(m.AuditLog.action == "evidence.viewed"))
    assert log and log.details == {"media_index": 0}


def test_media_requires_a_reviewing_role_and_auth(api, db):
    ad, up, rv = seeded(api, db)
    fid = first(api, rv)[0]["id"]
    assert api.get(f"/findings/{fid}/media/0").status_code == 401
    assert api.get(f"/findings/{fid}/media/0", headers=up).status_code == 403
    au = session_for(api, db, "auditor")
    assert api.get(f"/findings/{fid}/media/0", headers=au).status_code == 403
    assert api.get(f"/findings/{fid}", headers=au).status_code == 403
    assert api.get(f"/findings/{fid}/media/0", headers=ad).status_code == 200


def test_decision_updates_status_keeps_history_and_audits_without_note(api, db):
    _, _, rv = seeded(api, db)
    f = first(api, rv)[0]
    r = api.post(
        f"/findings/{f['id']}/decision",
        headers=rv,
        json={"decision": "dismissed", "reason": "common_word", "note": "מילה רגילה"},
    )
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert f["id"] not in {x["id"] for x in first(api, rv)}  # leaves the "new" queue
    assert f["id"] in {
        x["id"]
        for x in api.get(
            "/findings", headers=rv, params={"status_": "dismissed"}
        ).json()
    }
    d = api.get(f"/findings/{f['id']}", headers=rv).json()
    assert (
        d["status"] == "dismissed"
        and d["history"][0]["note"] == "מילה רגילה"
        and d["history"][0]["reason"] == "common_word"
    )
    # a second reviewer changes their mind: both decisions are kept
    api.post(
        f"/findings/{f['id']}/decision", headers=rv, json={"decision": "escalated"}
    )
    d = api.get(f"/findings/{f['id']}", headers=rv).json()
    assert [h["decision"] for h in d["history"]] == ["dismissed", "escalated"] and d[
        "status"
    ] == "escalated"
    raw = db.scalar(select(m.Review)).note_enc
    assert "מילה".encode() not in raw
    details = str(
        [
            a.details
            for a in db.scalars(
                select(m.AuditLog).where(m.AuditLog.action == "finding.decided")
            ).all()
        ]
    )
    assert "מילה" not in details and "common_word" in details


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "maybe"},
        {
            "decision": "confirmed",
            "reason": "common_word",
        },  # reasons are for dismissals
        {"decision": "dismissed", "reason": "whatever"},
        {"decision": "dismissed", "note": "x" * 2001},
        {"decision": "dismissed", "extra": 1},
        {},
    ],
)
def test_decision_validation(api, db, body):
    _, _, rv = seeded(api, db)
    fid = first(api, rv)[0]["id"]
    assert (
        api.post(f"/findings/{fid}/decision", headers=rv, json=body).status_code == 422
    )
    assert db.scalar(select(m.Review)) is None


@pytest.mark.parametrize(
    "role,ok",
    [("uploader", False), ("auditor", False), ("reviewer", True), ("admin", True)],
)
def test_decision_roles(api, db, role, ok):
    ad, up, rv = seeded(api, db)
    fid = first(api, rv)[0]["id"]
    h = {"reviewer": rv, "uploader": up, "admin": ad}.get(role) or session_for(
        api, db, role
    )
    r = api.post(f"/findings/{fid}/decision", headers=h, json={"decision": "confirmed"})
    assert (r.status_code == 200) == ok and (ok or r.status_code == 403)


def test_unknown_or_malformed_ids_404(api, db):
    _, _, rv = seeded(api, db)
    for path in (
        "/findings/not-a-uuid",
        "/findings/00000000-0000-0000-0000-000000000000",
    ):
        assert api.get(path, headers=rv).status_code == 404
        assert (
            api.post(
                path + "/decision", headers=rv, json={"decision": "confirmed"}
            ).status_code
            == 404
        )


def test_list_filters_ordering_and_paging(api, db):
    _, _, rv = seeded(api, db)
    allf = first(api, rv)
    scores = [x["score"] for x in allf]
    assert scores == sorted(scores, reverse=True)  # most suspicious first
    assert {x["kind"] for x in first(api, rv, kind="uniform")} == {"uniform"}
    assert {x["severity"] for x in first(api, rv, severity="high")} == {"high"}
    assert first(api, rv, platform="tiktok") == []
    page1, page2 = first(api, rv, limit=2), first(api, rv, limit=2, offset=2)
    assert len(page1) == 2 and not {x["id"] for x in page1} & {x["id"] for x in page2}


def test_stats(api, db):
    _, up, rv = seeded(api, db)
    s = api.get("/stats", headers=rv).json()
    assert (
        s["findings_by_status"]["new"] >= 3
        and s["open_by_severity"]["high"] >= 1
        and s["accounts_by_status"] == {"open": 1}
    )
    au = session_for(api, db, "auditor")
    assert api.get("/stats", headers=au).status_code == 200
    assert api.get("/stats", headers=up).status_code == 403
    assert "soldier_x" not in str(s) and "בסיס" not in str(s)  # aggregates only
