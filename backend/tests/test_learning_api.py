import pytest
from sqlalchemy import select

from app import models as m
from app.config import settings
from tests.test_auth_api import api, auth, db, enrol, env, make_user  # noqa: F401
from tests.test_import_api import session_for
from tests.test_learning import BIRD, UNIT, World, keys  # noqa: F401


def two_admins(api, db):
    a = session_for(api, db, "admin")
    make_user(db, "admin2@example.org", "admin")
    s2, _ = enrol(api, "admin2@example.org")
    return a, auth(s2)


def findings(api, h, **q):
    return api.get("/findings", headers=h, params=q).json()


ENDPOINTS = [
    ("get", "/learning/status"),
    ("get", "/learning/models"),
    ("post", "/learning/train"),
    ("post", "/learning/rollback"),
    ("get", "/learning/terms"),
    ("get", "/learning/term-suggestions"),
    ("get", "/learning/golden"),
    ("post", "/learning/golden"),
    ("post", "/watchlist"),
    ("post", "/learning/models/00000000-0000-0000-0000-000000000000/approve"),
    ("post", "/learning/models/00000000-0000-0000-0000-000000000000/activate"),
    ("post", "/learning/models/00000000-0000-0000-0000-000000000000/shadow"),
    ("get", "/learning/models/00000000-0000-0000-0000-000000000000/shadow-report"),
]


@pytest.mark.parametrize("role", ["uploader", "reviewer", "auditor"])
def test_learning_is_admin_only(api, db, role):
    h = session_for(api, db, role)
    for method, path in ENDPOINTS:
        assert getattr(api, method)(path, headers=h).status_code == 403, (role, path)


def test_learning_requires_authentication(api):
    for method, path in ENDPOINTS:
        assert getattr(api, method)(path).status_code == 401, path


def test_without_a_model_nothing_changes_for_reviewers(api, db):
    """The guarantee: until an administrator activates a model the system behaves exactly as before."""
    w = World(db)
    for i, base in enumerate([0.9, 0.4, 0.7, 0.2, 0.55]):
        w.finding(f"טקסט {i}", base=base, key=f"k{i}")
    db.commit()
    rv = session_for(api, db, "reviewer")
    rows = findings(api, rv)
    assert [r["score"] for r in rows] == [
        0.9,
        0.7,
        0.55,
        0.4,
        0.2,
    ]  # engine score order, as before
    assert all(r["adjusted_score"] is None and r["lane"] == "normal" for r in rows)
    fid = rows[0]["id"]
    d = api.get(f"/findings/{fid}", headers=rv).json()
    assert d["adjusted_score"] is None and d["learning"] == []
    assert db.scalars(select(m.LearningModel)).all() == []


def test_full_promotion_flow_through_the_api(api, db):
    w = World(db)
    w.labelled_set()
    bird = w.finding("ראיתי נשר ענק בשמיים", key="b").id
    unit = w.finding("יחידת נשר יוצאת מחר", key="u").id
    db.commit()
    a1, a2 = two_admins(api, db)
    rv = session_for(api, db, "reviewer")

    st = api.get("/learning/status", headers=a1).json()
    assert st["labels"] == 60 and st["active"] is None and st["required_approvals"] == 2

    t = api.post("/learning/train", headers=a1)
    assert (
        t.status_code == 201
        and t.json()["status"] == "candidate"
        and t.json()["metrics"]["blockers"] == []
    )
    mid = t.json()["id"]
    assert (
        api.post(f"/learning/models/{mid}/activate", headers=a1).json()["detail"]
        == "needs_more_approvals"
    )
    assert (
        api.post(f"/learning/models/{mid}/approve", headers=a1).json()["approvals"] == 1
    )
    assert (
        api.post(f"/learning/models/{mid}/approve", headers=a1).status_code == 409
    )  # same person twice
    assert (
        api.post(f"/learning/models/{mid}/approve", headers=a2).json()["approvals"] == 2
    )
    act = api.post(f"/learning/models/{mid}/activate", headers=a2)
    assert act.status_code == 200 and act.json()["status"] == "active"

    rows = {r["id"]: r for r in findings(api, rv)}
    assert rows[str(unit)]["adjusted_score"] > rows[str(bird)]["adjusted_score"] + 0.2
    assert (
        rows[str(bird)]["lane"] == "normal" and rows[str(unit)]["lane"] == "normal"
    )  # 0.3+ is not "low"
    assert all(r["status"] == "new" for r in rows.values())  # re-ranked, never decided
    order = [r["id"] for r in findings(api, rv)]
    assert order.index(str(unit)) < order.index(str(bird))
    # the low-priority lane starts below 0.25 and exists only while a model is active
    from decimal import Decimal

    db.expire_all()
    db.get(m.Finding, bird).adjusted_score = Decimal("0.2")
    db.commit()
    low = {r["id"]: r for r in findings(api, rv)}[str(bird)]
    assert (
        low["lane"] == "low" and low["status"] == "new"
    )  # still listed, still needs a person
    d = api.get(f"/findings/{bird}", headers=rv).json()
    assert d["adjusted_score"] is not None and any(
        "הקשר" in x or "החלטות" in x for x in d["learning"]
    )

    assert api.post("/learning/rollback", headers=a1).json() == {"to": "baseline"}
    assert all(r["adjusted_score"] is None for r in findings(api, rv))
    actions = {a.action for a in db.scalars(select(m.AuditLog)).all()}
    assert {
        "learning.trained",
        "learning.approved",
        "learning.activated",
        "learning.rolled_back",
    } <= actions


def test_training_without_enough_decisions_is_refused_clearly(api, db):
    a = session_for(api, db, "admin")
    r = api.post("/learning/train", headers=a)
    assert r.status_code == 422 and r.json()["detail"] == "insufficient_labels"


def test_uncertain_first_ordering_for_active_learning(api, db):
    w = World(db)
    for i, base in enumerate([0.95, 0.5, 0.05, 0.45]):
        w.finding(f"טקסט {i}", base=base, key=f"k{i}")
    db.commit()
    rv = session_for(api, db, "reviewer")
    assert [r["score"] for r in findings(api, rv, order="uncertain")] == [
        0.5,
        0.45,
        0.95,
        0.05,
    ]
    assert findings(api, rv, order="nonsense") == findings(
        api, rv
    )  # unknown order falls back to the default


def test_golden_cases_are_admin_managed_and_never_logged(api, db):
    a = session_for(api, db, "admin")
    assert (
        api.post(
            "/learning/golden",
            headers=a,
            json={"text": "המשפט הסודי שחייבים לתפוס", "kind": "codename"},
        ).status_code
        == 201
    )
    assert (
        api.post(
            "/learning/golden", headers=a, json={"text": "xx", "kind": "codename"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/learning/golden",
            headers=a,
            json={"text": "משפט תקין", "kind": "nonsense"},
        ).status_code
        == 422
    )
    listed = api.get("/learning/golden", headers=a).json()
    assert listed[0]["text"] == "המשפט הסודי שחייבים לתפוס"
    raw = db.scalar(select(m.GoldenCase)).text_enc
    assert "שחייבים".encode() not in raw
    assert "שחייבים" not in str(
        [x.details for x in db.scalars(select(m.AuditLog)).all()]
    )
    assert (
        api.delete(f"/learning/golden/{listed[0]['id']}", headers=a).status_code == 204
    )
    assert api.get("/learning/golden", headers=a).json() == []


def test_adding_a_suggested_term_to_the_watchlist(api, db):
    a = session_for(api, db, "admin")
    r = api.post(
        "/watchlist",
        headers=a,
        json={
            "term": "שקנאי",
            "aliases": ["השקנאי"],
            "kind": "codename",
            "severity": "high",
        },
    )
    assert (
        r.status_code == 201
        and r.json()["term"] == "שקנאי"
        and r.json()["severity"] == "high"
    )
    again = api.post("/watchlist", headers=a, json={"term": "שקנאי", "kind": "site"})
    assert (
        again.status_code == 201 and again.json()["id"] == r.json()["id"]
    )  # upsert, no duplicate
    assert len(api.get("/watchlist", headers=a).json()) == 1
    assert api.post("/watchlist", headers=a, json={"term": "x"}).status_code == 422
    assert "שקנאי" not in str([x.details for x in db.scalars(select(m.AuditLog)).all()])


def test_revoking_a_consent_through_the_api_retires_the_model(api, db):
    w = World(db)
    w.labelled_set()
    db.commit()
    a1, a2 = two_admins(api, db)
    mid = api.post("/learning/train", headers=a1).json()["id"]
    for h in (a1, a2):
        api.post(f"/learning/models/{mid}/approve", headers=h)
    assert api.post(f"/learning/models/{mid}/activate", headers=a1).status_code == 200
    cid = str(w.consent.id)
    assert api.post(f"/consents/{cid}/revoke", headers=a1).status_code == 200
    models = api.get("/learning/models", headers=a1).json()
    assert models[0]["status"] == "retired" and models[0]["note"] == "data_erased"
    assert api.get("/learning/status", headers=a1).json()["active"] is None


_ = settings
