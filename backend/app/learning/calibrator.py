"""The learned layer: a calibrator that re-ranks findings from reviewers' past decisions.

Principles (these are rules, not tuning):
* It only RE-RANKS. The engine's own ``score`` is never changed, and nothing is auto-dismissed.
* Exact, high-value signals are never demoted (classification markers, coordinates, GPS) and
  high-severity watch-list hits never fall into the low-priority lane on their own.
* Every adjusted score comes with a plain-Hebrew explanation of what it was based on.
* It is small and inspectable: counts per term / per kind, plus two tiny logistic regressions
  (hashed words around a match; colour features for the uniform heuristic). No external service.
"""

import math
import zlib
from dataclasses import dataclass, field

import numpy as np

from ..analysis.text import norm

DIM = 1 << 11  # hashed text features
LOW_LANE = (
    0.25  # below this a finding is listed in the "low priority" lane (still visible)
)
HIGH_SEVERITY_FLOOR = 0.35
PRIOR_K = 8.0  # weight of the engine score as a prior for a (kind, source) group
TERM_K = 4.0  # weight of the group estimate as a prior for one term
LR_WEIGHT = 0.5
MIN_TERM_LABELS = 3
UNIFORM_FEATURES = ("share", "h", "s", "v", "green")


@dataclass
class Example:
    kind: str
    source: str
    severity: str
    base: float  # the engine's score
    key: str = ""
    term_id: str | None = None
    snippet: str = ""
    features: dict | None = None
    label: int | None = None  # 1 = a person confirmed/escalated it, 0 = dismissed
    when: float = 0.0  # decision time (seconds), for time-ordered splits


# --- features -------------------------------------------------------------------------- #


def _h(token: str) -> int:
    return zlib.crc32(token.encode()) % DIM


def text_vector(ex: Example) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    toks = norm(ex.snippet).split()
    for t in toks:
        v[_h("u:" + t)] = 1.0
    for a, b in zip(toks, toks[1:]):
        v[_h(f"b:{a}_{b}")] = 1.0
    for extra in (
        f"kind:{ex.kind}",
        f"sev:{ex.severity}",
        f"src:{ex.source}",
        f"base:{int(ex.base * 10)}",
    ):
        v[_h(extra)] = 1.0
    if ex.term_id:
        v[_h("term:" + ex.term_id)] = 1.0
    return v


def uniform_vector(ex: Example) -> np.ndarray:
    f = ex.features or {}
    return np.array([float(f.get(k, 0.0)) for k in UNIFORM_FEATURES], dtype=np.float32)


# --- tiny logistic regression ------------------------------------------------------------ #


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_lr(
    X: np.ndarray, y: np.ndarray, l2: float = 0.05, steps: int = 400, lr: float = 0.5
):
    w = np.zeros(X.shape[1], dtype=np.float64)
    b = 0.0
    n = len(y)
    for _ in range(steps):
        p = _sigmoid(X @ w + b)
        g = p - y
        w -= lr * (X.T @ g / n + l2 * w)
        b -= lr * g.mean()
    return w, b


def auc(y, s) -> float | None:
    """Probability that a random positive outranks a random negative (ties count half)."""
    y = np.asarray(y)
    s = np.asarray(s, dtype=float)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    wins = (pos[:, None] > neg[None, :]).sum() + 0.5 * (
        pos[:, None] == neg[None, :]
    ).sum()
    return float(wins / (len(pos) * len(neg)))


# --- the calibrator --------------------------------------------------------------------- #


def _must_keep(ex: Example) -> bool:
    return ex.kind == "classified_document" or ex.key.startswith(
        ("marker", "coord", "exif")
    )


@dataclass
class Calibrator:
    group: dict[str, list[int]] = field(
        default_factory=dict
    )  # "kind|source" -> [positives, n]
    term: dict[str, list[int]] = field(
        default_factory=dict
    )  # term id -> [positives, n]
    text_lr: dict | None = None  # {"w": [...], "b": float, "val_auc": float}
    uniform_lr: dict | None = None

    # -- scoring ---------------------------------------------------------------------------
    def predict(self, ex: Example) -> tuple[float, list[str]]:
        reasons: list[str] = []
        pos, n = self.group.get(f"{ex.kind}|{ex.source}", [0, 0])
        p = (pos + PRIOR_K * ex.base) / (n + PRIOR_K)
        if n:
            reasons.append(f"בסוג התראה זה ({n} החלטות) אושרו {round(100 * pos / n)}%")
        if ex.term_id and ex.term_id in self.term:
            tpos, tn = self.term[ex.term_id]
            if tn >= MIN_TERM_LABELS:
                p = (tpos + TERM_K * p) / (tn + TERM_K)
                reasons.append(f"על מונח זה התקבלו {tn} החלטות, {tpos} מהן אושרו")
        lr, vec = self._lr_for(ex)
        if lr is not None:
            z = float(np.dot(np.asarray(lr["w"]), vec) + lr["b"])
            q = float(_sigmoid(z))
            p = (1 - LR_WEIGHT) * p + LR_WEIGHT * q
            reasons.append(
                "ההקשר דומה להתראות שאושרו בעבר"
                if q >= 0.5
                else "ההקשר דומה להתראות שנדחו בעבר"
            )
        if _must_keep(ex):
            p = max(p, ex.base)
            reasons.append(
                "אות מדויק (סימון סיווג, קואורדינטות או GPS) – לא מורידים את הציון"
            )
        if ex.severity == "high" and ex.term_id:
            p = max(p, HIGH_SEVERITY_FLOOR)
        return round(min(0.99, max(0.01, p)), 3), reasons

    def _lr_for(self, ex: Example):
        if ex.kind == "uniform" and self.uniform_lr:
            return self.uniform_lr, uniform_vector(ex)
        if ex.kind != "uniform" and self.text_lr and ex.snippet:
            return self.text_lr, text_vector(ex)
        return None, None

    # -- (de)serialisation -------------------------------------------------------------------
    def to_json(self) -> dict:
        return {
            "group": self.group,
            "term": self.term,
            "text_lr": self.text_lr,
            "uniform_lr": self.uniform_lr,
        }

    @classmethod
    def from_json(cls, d: dict) -> "Calibrator":
        return cls(
            d.get("group", {}), d.get("term", {}), d.get("text_lr"), d.get("uniform_lr")
        )


def _split(examples: list[Example], frac: float = 0.25):
    ordered = sorted(examples, key=lambda e: e.when)
    k = max(1, int(len(ordered) * frac))
    return ordered[:-k], ordered[-k:]


def _maybe_lr(examples, vec_fn, min_n: int = 30, min_val_class: int = 5) -> dict | None:
    """Train on the older part, keep the model only if it ranks the newer part clearly better
    than chance. Then refit on everything."""
    if len(examples) < min_n:
        return None
    train, val = _split(examples)
    yv = np.array([e.label for e in val])
    if (yv == 1).sum() < min_val_class or (yv == 0).sum() < min_val_class:
        return None
    X = np.stack([vec_fn(e) for e in train])
    y = np.array([e.label for e in train], dtype=np.float64)
    if y.sum() == 0 or y.sum() == len(y):
        return None
    w, b = fit_lr(X, y)
    scores = np.stack([vec_fn(e) for e in val]) @ w + b
    a = auc(yv, scores)
    if a is None or a < 0.6:
        return None
    Xa = np.stack([vec_fn(e) for e in examples])
    w, b = fit_lr(Xa, np.array([e.label for e in examples], dtype=np.float64))
    return {
        "w": [round(float(x), 5) for x in w],
        "b": round(float(b), 5),
        "val_auc": round(a, 3),
    }


def fit(examples: list[Example]) -> Calibrator:
    cal = Calibrator()
    for e in examples:
        g = cal.group.setdefault(f"{e.kind}|{e.source}", [0, 0])
        g[0] += int(e.label == 1)
        g[1] += 1
        if e.term_id:
            t = cal.term.setdefault(e.term_id, [0, 0])
            t[0] += int(e.label == 1)
            t[1] += 1
    cal.text_lr = _maybe_lr(
        [e for e in examples if e.kind != "uniform" and e.snippet], text_vector
    )
    cal.uniform_lr = _maybe_lr(
        [e for e in examples if e.kind == "uniform"], uniform_vector
    )
    return cal


def evaluate(cal: Calibrator, test: list[Example]) -> dict:
    y = [e.label for e in test]
    return {
        "n_test": len(test),
        "positives": int(sum(y)),
        "baseline_auc": auc(y, [e.base for e in test]),
        "model_auc": auc(y, [cal.predict(e)[0] for e in test]),
    }


_ = math
