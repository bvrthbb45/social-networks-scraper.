from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app import models as m
from app.maintenance import expire_consents
from tests.test_auth_api import api, auth, db, enrol, env, make_user  # noqa: F401
from tests.xlsx_helpers import TODAY, good_row, terms_workbook, workbook

XLSX = (
    "r.xlsx",
    None,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)


def session_for(api, db, role):
    make_user(db, f"{role}@example.org", role)
    s, _ = enrol(api, f"{role}@example.org")
    return auth(s)


def upload(api, h, rows, dry_run=False, path="/imports/roster"):
    data = workbook(rows) if not isinstance(rows, bytes) else rows
    return api.post(
        path,
        headers=h,
        files={"file": ("r.xlsx", data)},
        data={"dry_run": str(dry_run).lower()},
    )


def test_dry_run_keeps_nothing_and_is_the_default(api, db):
    h = session_for(api, db, "uploader")
    r = upload(api, h, [good_row(1), good_row(2)], dry_run=True)
    assert (
        r.status_code == 200
        and r.json()["accounts_created"] == 2
        and r.json()["import_id"] is None
    )
    assert db.scalar(select(m.Account)) is None and db.scalar(select(m.Soldier)) is None
    default = api.post(
        "/imports/roster",
        headers=h,
        files={"file": ("r.xlsx", workbook([good_row(1)]))},
    )
    assert default.json()["dry_run"] is True and db.scalar(select(m.Account)) is None


def test_commit_stores_encrypted_and_is_idempotent(api, db):
    h = session_for(api, db, "uploader")
    r = upload(api, h, [good_row(1), good_row(2, **{"סטטוס": "סגור"})]).json()
    assert r["soldiers_created"] == 2 and r["accounts_created"] == 2
    s = db.scalars(select(m.Soldier)).all()
    blob = b"".join(x.full_name_enc + x.personal_number_enc for x in s)
    assert (
        "חייל".encode() not in blob and b"7000001" not in blob
    )  # no plaintext at rest
    again = upload(api, h, [good_row(1), good_row(2, **{"סטטוס": "סגור"})]).json()
    assert (
        again["duplicate_file"]
        and again["soldiers_created"] == 0
        and again["unchanged"] == 2
    )
    assert len(db.scalars(select(m.Account)).all()) == 2


def test_status_change_updates_account(api, db):
    h = session_for(api, db, "uploader")
    upload(api, h, [good_row(1)])
    r = upload(api, h, [good_row(1, **{"סטטוס": "סגור"})]).json()
    assert r["accounts_updated"] == 1
    db.expire_all()
    assert db.scalar(select(m.Account)).status == "closed"


def test_account_of_another_soldier_is_refused(api, db):
    h = session_for(api, db, "uploader")
    upload(api, h, [good_row(1)])
    r = upload(api, h, [good_row(2, **{"חשבון": "test_user_1"})]).json()
    assert r["rejected"] == {"account_belongs_to_other_soldier": [2]}


def test_import_summary_never_contains_personal_data(api, db):
    h = session_for(api, db, "uploader")
    rows = [good_row(1), good_row(2, **{"אסמכתת הסכמה": ""})]
    r = upload(api, h, rows)
    blob = str(r.json()) + str(api.get("/imports", headers=h).json())
    for secret in ("חייל בדוי", "7000001", "test_user_1", "FORM-1"):
        assert secret not in blob
    audit = str([a.details for a in db.scalars(select(m.AuditLog)).all()])
    for secret in ("חייל בדוי", "7000001", "test_user_1"):
        assert secret not in audit


def test_bad_files_rejected_with_code_and_audited(api, db):
    h = session_for(api, db, "uploader")
    r = upload(api, h, b"not a workbook")
    assert r.status_code == 422 and r.json()["detail"] == "not_xlsx"
    big = api.post(
        "/imports/roster",
        headers=h,
        files={"file": ("r.xlsx", b"PK" + b"0" * (6 * 1024 * 1024))},
    )
    assert big.status_code == 413
    assert db.scalar(select(m.AuditLog).where(m.AuditLog.action == "import.rejected"))


@pytest.mark.parametrize(
    "role,allowed",
    [("uploader", True), ("admin", True), ("reviewer", False), ("auditor", False)],
)
def test_roster_upload_roles(api, db, role, allowed):
    h = session_for(api, db, role)
    r = upload(api, h, [good_row(1)], dry_run=True)
    assert (r.status_code == 200) == allowed and (allowed or r.status_code == 403)


def test_uploader_cannot_read_names_reviewer_can(api, db):
    up = session_for(api, db, "uploader")
    upload(api, up, [good_row(1)])
    assert api.get("/soldiers", headers=up).status_code == 403
    assert api.get("/accounts", headers=up).status_code == 403
    rv = session_for(api, db, "reviewer")
    rows = api.get("/soldiers", headers=rv).json()
    assert rows[0]["full_name"] == "חייל בדוי 1" and rows[0]["accounts"] == 1


def _seed_post(db, account):
    from datetime import datetime, timezone

    db.add(
        m.Post(
            account_id=account.id,
            content_hash="h",
            delete_after=datetime.now(timezone.utc) + timedelta(days=9),
        )
    )
    db.commit()


def test_revoking_consent_deletes_accounts_and_content(api, db):
    up = session_for(api, db, "uploader")
    upload(api, up, [good_row(1)])
    _seed_post(db, db.scalar(select(m.Account)))
    ad = session_for(api, db, "admin")
    cid = db.scalar(select(m.Consent)).id
    assert api.post(f"/consents/{cid}/revoke", headers=up).status_code == 403
    r = api.post(f"/consents/{cid}/revoke", headers=ad)
    assert r.status_code == 200 and r.json()["accounts_deleted"] == 1
    db.expire_all()
    assert db.scalar(select(m.Account)) is None and db.scalar(select(m.Post)) is None
    assert (
        db.scalar(select(m.Consent)).status == "revoked"
    )  # the record of consent stays
    assert api.post(f"/consents/{cid}/revoke", headers=ad).status_code == 409
    # a re-upload does not silently revive a revoked consent
    again = upload(api, up, [good_row(1)]).json()
    assert again["rejected"] == {"consent_revoked": [2]}
    assert db.scalar(select(m.Account)) is None


def test_erasing_a_soldier_removes_everything(api, db):
    up = session_for(api, db, "uploader")
    upload(api, up, [good_row(1)])
    _seed_post(db, db.scalar(select(m.Account)))
    ad = session_for(api, db, "admin")
    sid = db.scalar(select(m.Soldier)).id
    assert api.delete(f"/soldiers/{sid}", headers=up).status_code == 403
    assert api.delete(f"/soldiers/{sid}", headers=ad).status_code == 204
    db.expire_all()
    for model in (m.Soldier, m.Consent, m.Account, m.Post):
        assert db.scalar(select(model)) is None


def test_expiry_job_stops_monitoring(api, db):
    up = session_for(api, db, "uploader")
    upload(api, up, [good_row(1)])
    assert expire_consents(db, TODAY) == 0
    assert expire_consents(db, TODAY + timedelta(days=400)) == 1
    db.expire_all()
    assert (
        db.scalar(select(m.Account)) is None
        and db.scalar(select(m.Consent)).status == "expired"
    )


def test_watchlist_import_encrypted_admin_only(api, db):
    ad = session_for(api, db, "admin")
    data = terms_workbook(
        [
            ("נשר שחור", "הנשר; BlackEagle", "שם קוד", "גבוהה"),
            ("בסיס צפוני", "", "אתר", ""),
            ("x", "", "אתר", ""),
            ("שם", "", "???", ""),
        ]
    )
    r = api.post("/watchlist/import", headers=ad, files={"file": ("t.xlsx", data)})
    assert r.status_code == 200 and r.json()["created"] == 2
    assert set(r.json()["rejected"]) == {"bad_term", "bad_kind_or_severity"}
    raw = b"".join(
        t.term_enc + (t.aliases_enc or b"")
        for t in db.scalars(select(m.WatchlistTerm)).all()
    )
    assert "נשר".encode() not in raw and b"BlackEagle" not in raw
    listed = api.get("/watchlist", headers=ad).json()
    top = next(t for t in listed if t["term"] == "נשר שחור")
    assert top["aliases"] == ["הנשר", "BlackEagle"] and top["severity"] == "high"
    again = api.post(
        "/watchlist/import", headers=ad, files={"file": ("t.xlsx", data)}
    ).json()
    assert again["created"] == 0 and again["updated"] == 2  # upsert, no duplicates
    assert (
        str([a.details for a in db.scalars(select(m.AuditLog)).all()]).count("נשר") == 0
    )
    for role in ("uploader", "reviewer", "auditor"):
        h = session_for(api, db, role)
        assert api.get("/watchlist", headers=h).status_code == 403
        assert (
            api.post(
                "/watchlist/import", headers=h, files={"file": ("t.xlsx", data)}
            ).status_code
            == 403
        )
    tid = top["id"]
    assert (
        api.patch(f"/watchlist/{tid}", headers=ad, json={"active": False}).json()[
            "active"
        ]
        is False
    )
    assert api.delete(f"/watchlist/{tid}", headers=ad).status_code == 204
