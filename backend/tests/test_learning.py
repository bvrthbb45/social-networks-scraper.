import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import models as m
from app.config import settings
from app.learning import calibrator as C
from app.learning import service
from app.learning.calibrator import Calibrator, Example
from app.maintenance import end_consent
from app.security import crypto
from tests import factories as f
from tests.test_auth_api import api, auth, db, enrol, env, make_user  # noqa: F401
from tests.test_import_api import session_for

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
BIRD = [
    "ראיתי נשר בשמיים",
    "נשר גדול עף מעל ההר",
    "נשר ענק על הסלע",
    "צילמתי נשר ליד הנחל",
    "הנשר ריחף מעל העמק",
]
UNIT = [
    "יחידת נשר יוצאת מחר",
    "פקודה נשר מחר בבוקר",
    "נשר הגיעו לגזרה הצפונית",
    "תדריך נשר בשעה שבע",
    "כוח נשר בדרך לבסיס",
]


@pytest.fixture(autouse=True)
def keys(monkeypatch, env):  # noqa: F811
    monkeypatch.setattr(settings, "learning_min_labels", 40)
    monkeypatch.setattr(settings, "learning_required_approvals", 2)


class World:
    """Builds reviewed findings quickly (one open, consenting account unless told otherwise)."""

    def __init__(self, db, tag="main"):
        self.db = db
        self.consent = f.consent(
            db,
            valid_from=date.today() - timedelta(days=5),
            valid_until=date.today() + timedelta(days=100),
        )
        self.account = f.account(
            db, self.consent, status="open", username=f"acct_{tag}"
        )
        self.term = m.WatchlistTerm(
            id=uuid.uuid4(),
            term_hash=uuid.uuid4().hex * 2,
            term_enc=b"",
            kind="codename",
            severity="medium",
        )
        db.add(self.term)
        self.term.term_enc = crypto.encrypt_text(
            "נשר", f"watchlist_terms.term:{self.term.id}"
        )
        db.flush()
        self.n = 0

    def finding(
        self,
        snippet,
        label=None,
        *,
        kind="codename",
        base=0.55,
        severity="medium",
        key=None,
        term=True,
        account=None,
        text=None,
        features=None,
        source="text",
    ):
        db = self.db
        acct = account or self.account
        p = f.post(
            db, acct, delete_after=datetime.now(timezone.utc) + timedelta(days=30)
        )
        if text is not None:
            p.text_enc = crypto.encrypt_text(text, f"posts.text:{p.id}")
        fid = uuid.uuid4()
        ev = {
            "source": source,
            "snippet": snippet,
            "term_id": str(self.term.id) if term else None,
            "key": key or str(self.term.id),
            "features": features,
        }
        fnd = m.Finding(
            id=fid,
            post_id=p.id,
            kind=kind,
            score=Decimal(str(base)),
            severity=severity,
            reason_enc=crypto.encrypt_text("r", f"findings.reason:{fid}"),
            evidence_enc=crypto.encrypt_json(ev, f"findings.evidence:{fid}"),
            evidence_hash=uuid.uuid4().hex * 2,
        )
        db.add(fnd)
        db.flush()
        if label is not None:
            self.n += 1
            rid = uuid.uuid4()
            db.add(
                m.Review(
                    id=rid,
                    finding_id=fid,
                    reviewer_id=None,
                    decision="confirmed" if label else "dismissed",
                    reason=None if label else "common_word",
                    decided_at=T0 + timedelta(minutes=self.n),
                )
            )
            fnd.status = "confirmed" if label else "dismissed"
        db.flush()
        return fnd

    def labelled_set(self, n_pairs=30):
        """Bird contexts get dismissed, unit contexts confirmed; the engine score cannot tell them apart."""
        for i in range(n_pairs):
            self.finding(BIRD[i % len(BIRD)] + f" {i}", 0)
            self.finding(UNIT[i % len(UNIT)] + f" {i}", 1)
        self.db.commit()


# --- the calibrator ----------------------------------------------------------------------- #


def examples(world):
    return service.labeled_examples(world.db)


def test_calibrator_learns_that_context_separates_a_term(db):
    w = World(db)
    w.labelled_set()
    cal = C.fit(examples(w))
    bird = cal.predict(
        Example(
            "codename",
            "text",
            "medium",
            0.55,
            str(w.term.id),
            str(w.term.id),
            "ראיתי נשר ענק בשמיים",
        )
    )
    unit = cal.predict(
        Example(
            "codename",
            "text",
            "medium",
            0.55,
            str(w.term.id),
            str(w.term.id),
            "יחידת נשר יוצאת מחר",
        )
    )
    assert unit[0] > bird[0] + 0.2
    assert any("הקשר" in r for r in unit[1]) and any(
        "מונח זה" in r for r in unit[1]
    )  # explanations are plain Hebrew


def test_exact_signals_are_never_demoted_whatever_history_says():
    cal = Calibrator(
        group={
            "text_pattern|text": [0, 200],
            "location|text": [0, 200],
            "location|exif": [0, 200],
        }
    )
    for kind, source, key in (
        ("text_pattern", "text", "marker0"),
        ("location", "text", "coord1"),
        ("location", "exif", "exif-gps"),
    ):
        p, why = cal.predict(Example(kind, source, "high", 0.85, key))
        assert p >= 0.85 and any("לא מורידים" in r for r in why)


def test_high_severity_watchlist_hits_stay_out_of_the_low_lane():
    cal = Calibrator(term={"t": [0, 50]}, group={"codename|text": [0, 50]})
    assert (
        cal.predict(Example("codename", "text", "high", 0.6, "t", "t", ""))[0]
        >= C.HIGH_SEVERITY_FLOOR
    )
    assert (
        cal.predict(Example("codename", "text", "medium", 0.6, "t", "t", ""))[0]
        < C.LOW_LANE
    )


def test_little_history_barely_moves_the_engine_score():
    cal = C.fit(
        [Example("codename", "text", "medium", 0.6, "k", "t", "x", label=0, when=1.0)]
    )
    assert (
        abs(
            cal.predict(Example("codename", "text", "medium", 0.6, "k", "t", "x"))[0]
            - 0.6
        )
        < 0.1
    )


def test_auc_basics():
    assert C.auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == 1.0
    assert C.auc([1, 0], [0.5, 0.5]) == 0.5
    assert C.auc([1, 1], [0.5, 0.4]) is None


def test_uniform_colour_model_learns_from_features(db):
    w = World(db)
    for i in range(40):
        good = i % 2 == 0
        w.finding(
            "",
            int(good),
            kind="uniform",
            base=0.45,
            term=False,
            key="uniform-green",
            source="image",
            features={
                "share": 0.2 if good else 0.07,
                "edges": 1,
                "h": 0.2,
                "s": 0.4,
                "v": 0.3 if good else 0.7,
                "green": 1.0,
            },
        )
    db.commit()
    cal = C.fit(examples(w))
    hi = cal.predict(
        Example(
            "uniform",
            "image",
            "low",
            0.45,
            "uniform-green",
            None,
            "",
            {"share": 0.2, "h": 0.2, "s": 0.4, "v": 0.3, "green": 1.0},
        )
    )[0]
    lo = cal.predict(
        Example(
            "uniform",
            "image",
            "low",
            0.45,
            "uniform-green",
            None,
            "",
            {"share": 0.07, "h": 0.2, "s": 0.4, "v": 0.7, "green": 1.0},
        )
    )[0]
    assert cal.uniform_lr is not None and hi > lo


# --- training and promotion gates ---------------------------------------------------------- #


def test_training_needs_enough_labels_and_both_kinds_of_decision(db):
    w = World(db)
    with pytest.raises(service.LearningError) as e:
        service.train_candidate(db, None)
    assert e.value.code == "insufficient_labels"
    for i in range(45):
        w.finding(f"יחידת נשר {i}", 1)
    db.commit()
    with pytest.raises(service.LearningError) as e:
        service.train_candidate(db, None)
    assert e.value.code == "one_class_only"


def test_candidate_is_trained_measured_against_the_baseline_and_not_active(db):
    w = World(db)
    w.labelled_set()
    mod = service.train_candidate(db, None)
    assert mod.status == "candidate" and mod.trained_on == 60
    assert (
        mod.metrics["model_auc"] > mod.metrics["baseline_auc"] + 0.2
        and mod.metrics["blockers"] == []
    )
    assert service.active_model(db) is None
    assert crypto.decrypt_json(mod.params_enc, f"learning_models.params:{mod.id}")[
        "term"
    ]
    assert b"term" not in mod.params_enc  # parameters are encrypted at rest


def test_a_model_that_is_no_better_than_the_engine_is_blocked(db):
    w = World(db)
    for i in range(60):  # decisions unrelated to anything the model can see
        w.finding("אותו טקסט", i % 2, base=0.55)
    db.commit()
    mod = service.train_candidate(db, None)
    assert "not_better_than_baseline" in mod.metrics["blockers"]
    for _ in range(2):
        service.approve(db, mod, uuid.uuid4()) if False else None
    with pytest.raises(service.LearningError) as e:
        service.activate(db, mod)
    assert e.value.code == "not_better_than_baseline"


def make_admins(db, n=2):
    out = []
    for i in range(n):
        u = m.User(email=f"adm{i}@example.org", role="admin", password_hash="!")
        db.add(u)
        out.append(u)
    db.flush()
    return out


def test_promotion_needs_two_different_people(db):
    w = World(db)
    w.labelled_set()
    mod = service.train_candidate(db, None)
    a, b = make_admins(db)
    with pytest.raises(service.LearningError) as e:
        service.activate(db, mod)
    assert e.value.code == "needs_more_approvals"
    assert service.approve(db, mod, a.id) == 1
    with pytest.raises(service.LearningError) as e:
        service.approve(db, mod, a.id)  # the same person cannot approve twice
    assert e.value.code == "already_approved"
    with pytest.raises(service.LearningError):
        service.activate(db, mod)
    assert service.approve(db, mod, b.id) == 2
    service.activate(db, mod)
    assert mod.status == "active" and service.active_model(db).id == mod.id


def test_activation_reranks_open_findings_but_decides_nothing(db):
    w = World(db)
    w.labelled_set()
    bird = w.finding("ראיתי נשר ענק בשמיים")
    unit = w.finding("יחידת נשר יוצאת מחר")
    db.commit()
    mod = service.train_candidate(db, None)
    for u in make_admins(db):
        service.approve(db, mod, u.id)
    service.activate(db, mod)
    db.refresh(bird), db.refresh(unit)
    assert float(unit.adjusted_score) > float(bird.adjusted_score) + 0.2
    assert (
        float(bird.score) == float(unit.score) == 0.55
    )  # the engine's own score is untouched
    assert (
        bird.status == "new" and unit.status == "new"
    )  # nothing was dismissed or confirmed by the model
    assert bird.scored_by_model == mod.id


def test_newer_model_replaces_older_and_rollback_restores_it(db):
    w = World(db)
    w.labelled_set()
    admins = make_admins(db)
    first = service.train_candidate(db, None)
    for u in admins:
        service.approve(db, first, u.id)
    service.activate(db, first)
    w.finding("נשר נוסף", 1)
    db.commit()
    second = service.train_candidate(db, None)
    for u in admins:
        service.approve(db, second, u.id)
    service.activate(db, second)
    db.refresh(first)
    assert (
        first.status == "retired"
        and first.note == "replaced"
        and service.active_model(db).id == second.id
    )
    assert (
        service.rollback(db) == "previous" and service.active_model(db).id == first.id
    )
    assert service.rollback(db) == "baseline" and service.active_model(db) is None
    open_f = db.scalars(select(m.Finding).where(m.Finding.status == "new")).all()
    assert all(x.adjusted_score is None for x in open_f)  # back to plain engine scores
    with pytest.raises(service.LearningError):
        service.rollback(db)


def test_golden_must_catch_cases_block_a_model_that_would_bury_them(db):
    w = World(db)
    for i in range(
        60
    ):  # this term is dismissed 5 times out of 6, almost always in bird contexts
        confirmed = i % 6 == 0
        w.finding((UNIT if confirmed else BIRD)[i % 5] + f" {i}", int(confirmed))
    db.commit()
    # the admin insists that this bird-like sentence must always be caught
    gid = uuid.uuid4()
    db.add(
        m.GoldenCase(
            id=gid,
            kind="codename",
            text_enc=crypto.encrypt_text(
                "ראיתי נשר ענק בשמיים", f"golden_cases.text:{gid}"
            ),
        )
    )
    db.commit()
    mod = service.train_candidate(db, None)
    assert "golden_failed" in mod.metrics["blockers"]
    for u in make_admins(db):
        service.approve(db, mod, u.id)
    with pytest.raises(service.LearningError) as e:
        service.activate(db, mod)
    assert e.value.code == "golden_failed"


def test_builtin_golden_cases_are_detected_by_the_engine():
    cal = Calibrator()
    assert service.golden_failures(cal, [], service.BUILTIN_GOLDEN) == []


# --- erasure and consent -------------------------------------------------------------------- #


def test_erasing_reviewed_data_retires_models_and_restores_engine_scores(db):
    w = World(db)
    w.labelled_set()
    other = f.account(db, w.consent, status="open", username="acct_other")
    keep = w.finding("ראיתי נשר ענק בשמיים", account=other)
    db.commit()
    mod = service.train_candidate(db, None)
    for u in make_admins(db):
        service.approve(db, mod, u.id)
    service.activate(db, mod)
    db.refresh(keep)
    assert keep.adjusted_score is not None
    end_consent(
        db, w.consent, "revoked", None
    )  # revokes ALL accounts under that consent (both)
    db.commit()
    db.refresh(mod)
    assert (
        mod.status == "retired"
        and mod.note == "data_erased"
        and service.active_model(db) is None
    )


def test_erasing_accounts_nobody_reviewed_keeps_the_model(db):
    w = World(db)
    w.labelled_set()
    mod = service.train_candidate(db, None)
    for u in make_admins(db):
        service.approve(db, mod, u.id)
    service.activate(db, mod)
    c2 = f.consent(
        db,
        valid_from=date.today() - timedelta(days=5),
        valid_until=date.today() + timedelta(days=100),
    )
    a2 = f.account(db, c2, status="open", username="acct_unreviewed")
    w.finding("טקסט שלא נבדק", account=a2)
    db.commit()
    end_consent(db, c2, "revoked", None)
    db.commit()
    db.refresh(mod)
    assert mod.status == "active"  # nothing was learned from them


def test_retraining_after_erasure_uses_only_what_remains(db):
    w = World(db)
    w.labelled_set(25)
    other = f.account(db, w.consent, status="open", username="acct_other")
    for i in range(30):
        w.finding(UNIT[i % 5] + f" extra {i}", 1, account=other)
    db.commit()
    assert len(examples(w)) == 80
    c2_ids = [other.id]
    from sqlalchemy import delete

    db.execute(delete(m.Account).where(m.Account.id.in_(c2_ids)))
    db.commit()
    assert len(examples(w)) == 50  # the examples of the erased account are simply gone


# --- shadow mode ------------------------------------------------------------------------------ #


def test_shadow_model_scores_silently_and_is_compared_with_the_engine(db):
    w = World(db)
    w.labelled_set()
    mod = service.train_candidate(db, None)
    service.start_shadow(db, mod)
    new = [w.finding(BIRD[i % 5] + f" s{i}") for i in range(6)] + [
        w.finding(UNIT[i % 5] + f" s{i}") for i in range(6)
    ]
    service.score_findings(db, new)
    db.commit()
    assert all(
        x.adjusted_score is None
        and x.shadow_score is not None
        and x.shadow_model == mod.id
        for x in new
    )
    for i, x in enumerate(
        new
    ):  # reviewers decide: bird -> dismissed, unit -> confirmed
        w.n += 1
        label = 0 if i < 6 else 1
        db.add(
            m.Review(
                finding_id=x.id,
                decision="confirmed" if label else "dismissed",
                decided_at=T0 + timedelta(days=1, minutes=w.n),
            )
        )
    db.commit()
    rep = service.shadow_report(db, mod)
    assert rep["n_decided"] == 12 and rep["shadow_auc"] > rep["baseline_auc"]


# --- what decisions say about the watch-list ---------------------------------------------------- #


def test_term_statistics_flag_noisy_and_effective_terms(db):
    w = World(db)
    for i in range(8):
        w.finding(f"ראיתי נשר {i}", 0)
    other = m.WatchlistTerm(
        id=uuid.uuid4(),
        term_hash="o" * 64,
        term_enc=b"",
        kind="codename",
        severity="high",
    )
    db.add(other)
    other.term_enc = crypto.encrypt_text("עורב", f"watchlist_terms.term:{other.id}")
    db.flush()
    saved = w.term
    w.term = other
    for i in range(6):
        w.finding(f"עורב {i}", 1)
    w.term = saved
    db.commit()
    stats = {s["term"]: s for s in service.term_stats(db)}
    assert stats["נשר"]["advice"] == "mostly_false_alarms" and stats["נשר"][
        "dismiss_reasons"
    ] == {"common_word": 8}
    assert stats["עורב"]["advice"] == "effective" and stats["עורב"]["precision"] == 1.0


def _confirmed_post(w, word, account, n=1):
    for i in range(n):
        w.finding(
            "x",
            1,
            account=account,
            text=f"דיברו על {word} בבסיס ועל משהו {i}",
            term=False,
            kind="text_pattern",
            key=f"marker{i}",
        )


def test_term_suggestions_respect_k_anonymity_and_exclude_common_words(db):
    w = World(db)
    a2 = f.account(db, w.consent, status="open", username="acct_two")
    a3 = f.account(db, w.consent, status="open", username="acct_three")
    _confirmed_post(w, "שקנאי", w.account, 2)
    _confirmed_post(w, "שקנאי", a2, 1)  # 3 posts, 2 accounts -> offered
    _confirmed_post(
        w, "חמסין", w.account, 4
    )  # 4 posts but ONE account -> never offered
    _confirmed_post(w, "נדיר", a3, 1)  # a single post -> never offered
    for i in range(10):
        w.finding(
            "x",
            0,
            text=f"טקסט רגיל שמזכיר שקנאי ובסיס מספר {i}",
            term=False,
            kind="text_pattern",
            key=f"m{i}",
            account=a3,
        )
    db.commit()
    out = {s["token"] for s in service.term_suggestions(db)}
    assert (
        "שקנאי" not in out
    )  # also frequent in dismissed posts (10/10 > 30%): a common word, not a code name
    assert "חמסין" not in out and "נדיר" not in out
    w2 = World(db, tag="second")
    b2 = f.account(db, w2.consent, status="open", username="acct_b2")
    _confirmed_post(w2, "אלפא", w2.account, 2)
    _confirmed_post(w2, "אלפא", b2, 1)
    db.commit()
    sug = service.term_suggestions(db)
    hit = next(s for s in sug if s["token"] == "אלפא")
    assert hit["confirmed_posts"] == 3 and hit["accounts"] == 2
    assert set(hit) == {
        "token",
        "confirmed_posts",
        "accounts",
        "dismissed_posts",
    }  # counts only, never post text


def test_suggestions_skip_words_already_on_the_watchlist(db):
    w = World(db)
    b2 = f.account(db, w.consent, status="open", username="acct_b2")
    _confirmed_post(w, "נשר", w.account, 2)
    _confirmed_post(w, "נשר", b2, 1)
    db.commit()
    assert "נשר" not in {s["token"] for s in service.term_suggestions(db)}


def test_golden_gate_is_checked_again_at_activation_not_only_at_training(
    db, monkeypatch
):
    """The golden set or the policy can change between training and promotion."""
    w = World(db)
    w.labelled_set()
    mod = service.train_candidate(db, None)
    assert mod.metrics["blockers"] == []  # clean when trained
    for u in make_admins(db):
        service.approve(db, mod, u.id)
    gid = uuid.uuid4()
    db.add(
        m.GoldenCase(
            id=gid,
            kind="codename",
            text_enc=crypto.encrypt_text(
                "ראיתי נשר ענק בשמיים", f"golden_cases.text:{gid}"
            ),
        )
    )
    db.commit()
    monkeypatch.setattr(
        service, "GOLDEN_FLOOR", 0.5
    )  # a stricter must-catch policy than when it was trained
    with pytest.raises(service.LearningError) as e:
        service.activate(db, mod)
    assert e.value.code == "golden_failed" and service.active_model(db) is None
