"""Database side of learning: build the training set from reviews, train, gate, promote, roll back.

Training data is DERIVED from findings + reviews at training time and is never copied anywhere:
when an account's consent is revoked (or a soldier erased) its findings disappear and so do the
examples. Models trained before that are retired by ``invalidate_for_erasure`` so nothing learned
from erased data stays in force.
"""

import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analysis.text import Hit, TermSpec, analyze_text, norm
from ..config import settings
from ..models import (
    Account,
    Finding,
    GoldenCase,
    LearningModel,
    ModelApproval,
    Post,
    Review,
    WatchlistTerm,
)
from ..security import crypto
from . import calibrator as cal_mod
from .calibrator import LOW_LANE, Calibrator, Example

NEGATIVE = ("dismissed",)
POSITIVE = ("confirmed", "escalated")
GOLDEN_FLOOR = 0.30  # a must-catch example must stay at least this visible
MIN_AUC_GAIN = 0.02
BUILTIN_GOLDEN = [
    ("המסמך הזה סודי ביותר", "text_pattern"),
    ("הקואורדינטות 32.0853, 34.7818", "location"),
    ("https://maps.app.goo.gl/abc123", "location"),
    ('מסומן בלמ"ס', "text_pattern"),
]


class LearningError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- examples ------------------------------------------------------------------------------ #


def example_from_finding(
    f: Finding, label: int | None = None, when: float = 0.0
) -> Example:
    ev = (
        crypto.decrypt_json(f.evidence_enc, f"findings.evidence:{f.id}")
        if f.evidence_enc
        else {}
    )
    return Example(
        kind=f.kind,
        source=ev.get("source") or "text",
        severity=f.severity,
        base=float(f.score),
        key=ev.get("key") or "",
        term_id=ev.get("term_id"),
        snippet=ev.get("snippet") or "",
        features=ev.get("features"),
        label=label,
        when=when,
    )


def example_from_hit(h: Hit) -> Example:
    return Example(
        h.kind, h.source, h.severity, h.score, h.key, h.term_id, h.snippet, h.features
    )


def labeled_examples(db: Session) -> list[Example]:
    """One example per reviewed finding, labelled by the LATEST human decision."""
    latest: dict[uuid.UUID, Review] = {}
    for r in db.scalars(select(Review).order_by(Review.decided_at)).all():
        latest[r.finding_id] = r
    out = []
    for fid, r in latest.items():
        f = db.get(Finding, fid)
        if f is None:
            continue
        when = r.decided_at.replace(
            tzinfo=r.decided_at.tzinfo or timezone.utc
        ).timestamp()
        out.append(example_from_finding(f, 1 if r.decision in POSITIVE else 0, when))
    return out


# --- active model ---------------------------------------------------------------------------- #


def _params(m: LearningModel) -> Calibrator:
    return Calibrator.from_json(
        crypto.decrypt_json(m.params_enc, f"learning_models.params:{m.id}")
    )


def active_model(db: Session) -> LearningModel | None:
    return db.scalar(select(LearningModel).where(LearningModel.status == "active"))


def shadow_model(db: Session) -> LearningModel | None:
    return db.scalar(select(LearningModel).where(LearningModel.status == "shadow"))


def effective_score(f: Finding) -> float:
    return float(f.adjusted_score if f.adjusted_score is not None else f.score)


def score_findings(db: Session, findings: list[Finding]) -> None:
    """Called for new findings: fill ``adjusted_score`` (active model) and ``shadow_score``."""
    active, shadow = active_model(db), shadow_model(db)
    ac = _params(active) if active else None
    sc = _params(shadow) if shadow else None
    for f in findings:
        ex = example_from_finding(f)
        if ac:
            f.adjusted_score, f.scored_by_model = (
                cal_mod_round(ac.predict(ex)[0]),
                active.id,
            )
        if sc:
            f.shadow_score, f.shadow_model = cal_mod_round(sc.predict(ex)[0]), shadow.id


def cal_mod_round(x: float):
    from decimal import Decimal

    return Decimal(str(round(x, 3)))


def rescore_open(db: Session) -> int:
    """After the active model changes: re-rank findings nobody has decided yet."""
    active = active_model(db)
    ac = _params(active) if active else None
    n = 0
    for f in db.scalars(
        select(Finding).where(Finding.status.in_(("new", "in_review")))
    ).all():
        if ac:
            f.adjusted_score, f.scored_by_model = (
                cal_mod_round(ac.predict(example_from_finding(f))[0]),
                active.id,
            )
        else:
            f.adjusted_score, f.scored_by_model = None, None
        n += 1
    db.flush()
    return n


def explain(db: Session, f: Finding) -> list[str]:
    if f.scored_by_model is None:
        return []
    m = db.get(LearningModel, f.scored_by_model)
    if m is None:
        return []
    return _params(m).predict(example_from_finding(f))[1]


# --- golden cases ---------------------------------------------------------------------------- #


def golden_cases(db: Session) -> list[tuple[str, str]]:
    own = [
        (crypto.decrypt_text(g.text_enc, f"golden_cases.text:{g.id}"), g.kind)
        for g in db.scalars(select(GoldenCase)).all()
    ]
    return BUILTIN_GOLDEN + own


def load_terms(db: Session) -> list[TermSpec]:
    from ..analysis.pipeline import load_terms as _load

    return _load(db)


def golden_failures(
    cal: Calibrator, terms: list[TermSpec], cases: list[tuple[str, str]]
) -> list[int]:
    """Indexes of must-catch cases that the engine misses or that ``cal`` would push below the floor."""
    bad = []
    for i, (text, kind) in enumerate(cases):
        hits = [h for h in analyze_text(text, terms) if h.kind == kind]
        if (
            not hits
            or max(cal.predict(example_from_hit(h))[0] for h in hits) < GOLDEN_FLOOR
        ):
            bad.append(i)
    return bad


# --- training -------------------------------------------------------------------------------- #


def train_candidate(db: Session, user_id: uuid.UUID | None) -> LearningModel:
    examples = labeled_examples(db)
    n = len(examples)
    if n < settings.learning_min_labels:
        raise LearningError("insufficient_labels")
    positives = sum(e.label for e in examples)
    if positives == 0 or positives == n:
        raise LearningError("one_class_only")
    ordered = sorted(examples, key=lambda e: e.when)
    cut = max(1, int(n * 0.8))
    train, test = ordered[:cut], ordered[cut:]
    trial = cal_mod.fit(train)
    metrics = cal_mod.evaluate(trial, test)
    final = cal_mod.fit(examples)  # the shipped model learns from everything
    blockers = []
    if metrics["model_auc"] is None or metrics["baseline_auc"] is None:
        blockers.append("holdout_one_class")
    elif metrics["model_auc"] < metrics["baseline_auc"] + MIN_AUC_GAIN:
        blockers.append("not_better_than_baseline")
    failing = golden_failures(final, load_terms(db), golden_cases(db))
    if failing:
        blockers.append("golden_failed")
    metrics.update(
        {
            "n_labels": n,
            "positives": int(positives),
            "golden_failed": len(failing),
            "blockers": blockers,
            "text_lr": bool(final.text_lr),
            "uniform_lr": bool(final.uniform_lr),
        }
    )
    version = (db.scalar(select(func.max(LearningModel.version))) or 0) + 1
    mid = uuid.uuid4()
    m = LearningModel(
        id=mid,
        version=version,
        status="candidate",
        trained_on=n,
        metrics=metrics,
        trained_by=user_id,
        params_enc=crypto.encrypt_json(
            final.to_json(), f"learning_models.params:{mid}"
        ),
    )
    db.add(m)
    db.flush()
    return m


def approvals(db: Session, m: LearningModel) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ModelApproval)
            .where(ModelApproval.model_id == m.id)
        )
        or 0
    )


def approve(db: Session, m: LearningModel, user_id: uuid.UUID) -> int:
    if m.status not in ("candidate", "shadow"):
        raise LearningError("not_approvable")
    if db.scalar(
        select(ModelApproval.id).where(
            ModelApproval.model_id == m.id, ModelApproval.user_id == user_id
        )
    ):
        raise LearningError("already_approved")
    db.add(ModelApproval(model_id=m.id, user_id=user_id))
    db.flush()
    return approvals(db, m)


def start_shadow(db: Session, m: LearningModel) -> None:
    if m.status not in ("candidate",):
        raise LearningError("not_a_candidate")
    old = shadow_model(db)
    if old:
        old.status = "candidate"
    m.status = "shadow"
    db.flush()


def activate(db: Session, m: LearningModel) -> None:
    if m.status not in ("candidate", "shadow"):
        raise LearningError("not_activatable")
    blockers = list((m.metrics or {}).get("blockers", []))
    if blockers:
        # safety first: a model that would bury a must-catch case is reported as that, whatever else is wrong
        raise LearningError(
            "golden_failed" if "golden_failed" in blockers else blockers[0]
        )
    # the golden gate is re-run NOW: the watch-list and golden set may have changed since training
    if golden_failures(_params(m), load_terms(db), golden_cases(db)):
        raise LearningError("golden_failed")
    if approvals(db, m) < settings.learning_required_approvals:
        raise LearningError("needs_more_approvals")
    cur = active_model(db)
    if cur:
        cur.status, cur.retired_at, cur.note = (
            "retired",
            datetime.now(timezone.utc),
            "replaced",
        )
    m.status, m.activated_at = "active", datetime.now(timezone.utc)
    db.flush()
    rescore_open(db)


def rollback(db: Session) -> str:
    """Back to the previous model, or to the plain engine scores if there is none."""
    cur = active_model(db)
    if cur is None:
        raise LearningError("nothing_active")
    cur.status, cur.retired_at, cur.note = (
        "retired",
        datetime.now(timezone.utc),
        "rollback",
    )
    previous = db.scalar(
        select(LearningModel)
        .where(LearningModel.status == "retired", LearningModel.note == "replaced")
        .order_by(LearningModel.activated_at.desc())
    )
    if previous:
        previous.status, previous.retired_at, previous.note = "active", None, None
    db.flush()
    rescore_open(db)
    return "previous" if previous else "baseline"


def reviewed_findings_of(db: Session, account_ids) -> int:
    """How many reviewed findings belong to these accounts (i.e. how much they could have taught)."""
    if not account_ids:
        return 0
    return (
        db.scalar(
            select(func.count(func.distinct(Review.finding_id)))
            .join(Finding, Finding.id == Review.finding_id)
            .join(Post, Post.id == Finding.post_id)
            .where(Post.account_id.in_(list(account_ids)))
        )
        or 0
    )


def invalidate_for_erasure(db: Session) -> int:
    """Data was erased (consent revoked / person deleted / retention). Whatever was learned from it
    must not stay in force: retire active and shadow models; the plain engine takes over until a
    new model is trained from what remains."""
    n = 0
    for m in db.scalars(
        select(LearningModel).where(
            LearningModel.status.in_(("active", "shadow", "candidate"))
        )
    ).all():
        m.status, m.retired_at, m.note = (
            "retired",
            datetime.now(timezone.utc),
            "data_erased",
        )
        n += 1
    if n:
        db.flush()
        rescore_open(db)
    return n


def shadow_report(db: Session, m: LearningModel) -> dict:
    """How would this model have ranked what reviewers have since decided, compared with the engine?"""
    rows = db.execute(
        select(Finding, Review)
        .join(Review, Review.finding_id == Finding.id)
        .where(Finding.shadow_model == m.id)
    ).all()
    latest: dict[uuid.UUID, tuple[Finding, Review]] = {}
    for f, r in sorted(rows, key=lambda x: x[1].decided_at):
        latest[f.id] = (f, r)
    y = [1 if r.decision in POSITIVE else 0 for f, r in latest.values()]
    return {
        "n_decided": len(y),
        "baseline_auc": cal_mod.auc(y, [float(f.score) for f, _ in latest.values()]),
        "shadow_auc": (
            cal_mod.auc(
                y,
                [
                    float(f.shadow_score)
                    for f, _ in latest.values()
                    if f.shadow_score is not None
                ],
            )
            if all(f.shadow_score is not None for f, _ in latest.values())
            else None
        ),
    }


# --- what the decisions say about the watch-list ------------------------------------------------ #


def term_stats(db: Session) -> list[dict]:
    stats: dict[str, dict] = {}
    for e in labeled_examples(db):
        if not e.term_id:
            continue
        s = stats.setdefault(e.term_id, {"n": 0, "confirmed": 0})
        s["n"] += 1
        s["confirmed"] += e.label or 0
    reasons: dict[str, Counter] = {}
    latest: dict[uuid.UUID, Review] = {}
    for r in db.scalars(select(Review).order_by(Review.decided_at)).all():
        latest[r.finding_id] = r
    for fid, r in latest.items():
        f = db.get(Finding, fid)
        if f is None or r.decision != "dismissed" or not r.reason:
            continue
        tid = example_from_finding(f).term_id
        if tid:
            reasons.setdefault(tid, Counter())[r.reason] += 1
    out = []
    for tid, s in stats.items():
        t = db.get(WatchlistTerm, uuid.UUID(tid))
        if t is None:
            continue
        precision = s["confirmed"] / s["n"]
        advice = None
        if s["n"] >= 5 and precision <= 0.2:
            advice = "mostly_false_alarms"
        elif s["n"] >= 5 and precision >= 0.8:
            advice = "effective"
        out.append(
            {
                "id": tid,
                "term": crypto.decrypt_text(t.term_enc, f"watchlist_terms.term:{t.id}"),
                "severity": t.severity,
                "n": s["n"],
                "confirmed": s["confirmed"],
                "precision": round(precision, 3),
                "advice": advice,
                "dismiss_reasons": dict(reasons.get(tid, {})),
            }
        )
    return sorted(out, key=lambda x: -x["n"])


_STOP = set(
    "של על עם את זה זו זאת הוא היא הם הן אני אנחנו אתה את אתם גם אבל כי לא כן יש אין היה היו אז כל מה מי איך למה איפה מאוד רק עוד כבר או אם".split()
)


def term_suggestions(
    db: Session, min_posts: int = 3, min_accounts: int = 2
) -> list[dict]:
    """Words that keep showing up in posts reviewers CONFIRMED and rarely in dismissed ones, that are
    not on the watch-list yet. k-anonymity: a word is only offered when it was seen in at least
    ``min_posts`` confirmed posts from at least ``min_accounts`` different accounts, and only counts
    (never post text) are returned. A person (admin) decides whether it becomes a term.
    """
    known = set()
    for t in load_terms(db):
        for form in (t.term, *t.aliases):
            known.update(norm(form).split())
    conf_posts: dict[str, set] = {}
    conf_accts: dict[str, set] = {}
    dis_posts: dict[str, set] = {}
    latest: dict[uuid.UUID, Review] = {}
    for r in db.scalars(select(Review).order_by(Review.decided_at)).all():
        latest[r.finding_id] = r
    seen_post: set[tuple[uuid.UUID, int]] = set()
    n_dismissed_posts = 0
    for fid, r in latest.items():
        f = db.get(Finding, fid)
        if f is None:
            continue
        post = db.get(Post, f.post_id)
        label = 1 if r.decision in POSITIVE else 0
        if (post.id, label) in seen_post or not post.text_enc:
            continue
        seen_post.add((post.id, label))
        toks = {
            t
            for t in norm(
                crypto.decrypt_text(post.text_enc, f"posts.text:{post.id}")
            ).split()
            if len(t) >= 3 and t not in _STOP and not re.fullmatch(r"\d+", t)
        }
        if label:
            for t in toks:
                conf_posts.setdefault(t, set()).add(post.id)
                conf_accts.setdefault(t, set()).add(post.account_id)
        else:
            n_dismissed_posts += 1
            for t in toks:
                dis_posts.setdefault(t, set()).add(post.id)
    out = []
    for t, posts in conf_posts.items():
        if t in known or len(posts) < min_posts or len(conf_accts[t]) < min_accounts:
            continue
        d = len(dis_posts.get(t, ()))
        if n_dismissed_posts and d / n_dismissed_posts > 0.3:
            continue  # a word that is everywhere is not a code name
        out.append(
            {
                "token": t,
                "confirmed_posts": len(posts),
                "accounts": len(conf_accts[t]),
                "dismissed_posts": d,
            }
        )
    return sorted(out, key=lambda x: (-x["confirmed_posts"], x["dismissed_posts"]))[:50]


_ = (Account, LOW_LANE)
