"""Text engines. Pure functions, no database, no network, no external AI service.

Every engine returns ``Hit`` objects: a lead for a human reviewer, never a verdict.
Hebrew specifics handled here: niqqud, final letters, geresh/gershayim ("בלמ"ס"),
one- or two-letter prefixes (ב/ה/ל/מ/ש/ו/כ: "בנשר" = "in Nesher"), typos (edit distance 1 on
longer terms) and simple obfuscation ("נ.ש.ר", "נ ש ר").
"""

import re
import unicodedata
from dataclasses import dataclass

from ..security.crypto import normalize as _base_normalize

PREFIXES = "בהלמשוכ"
_FINALS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})
_QUOTES = re.compile(r"[\"'`´׳״‘’“”]")
_NON_WORD = re.compile(r"[^0-9a-zA-Zא-ת]+")


@dataclass(frozen=True)
class TermSpec:
    id: str
    term: str
    aliases: tuple[str, ...]
    kind: str  # codename | site | unit | other
    severity: str  # low | medium | high


@dataclass(frozen=True)
class Hit:
    kind: str  # one of models.FINDING_KINDS
    severity: str
    score: float
    reason: str  # Hebrew, shown to the reviewer
    source: str  # "text" | "ocr" | "exif" | "image"
    snippet: str = ""
    term_id: str | None = None
    key: str = ""  # stable identity of the match (idempotency)


def norm(text: str) -> str:
    """Matching form: base normalisation, final letters unified, quotes dropped, words only."""
    t = _base_normalize(text).translate(_FINALS)
    t = _QUOTES.sub("", t)
    return _NON_WORD.sub(" ", t).strip()


_L = "0-9a-zA-Z\u05d0-\u05ea"
_DOTTED = re.compile(rf"(?<![{_L}])(?:[{_L}][.\-_*·]){{2,}}[{_L}](?![{_L}])")
_SPACED = re.compile(rf"(?<![{_L}])(?:[{_L}] ){{2,}}[{_L}](?![{_L}])")


def deobfuscate(text: str) -> str:
    """Join single letters split by dots/dashes ("נ.ש.ר") or by single spaces ("נ ש ר")."""
    t = _base_normalize(text).translate(_FINALS)
    t = _DOTTED.sub(lambda m: re.sub(r"[.\-_*·]", "", m.group(0)), t)
    return _SPACED.sub(lambda m: m.group(0).replace(" ", ""), t)


def _within_one_edit(a: str, b: str) -> bool:
    """Damerau-Levenshtein distance <= 1 (substitution, insertion, deletion, transposition)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return (
            len(diff) == 2
            and diff[1] == diff[0] + 1
            and a[diff[0]] == b[diff[1]]
            and a[diff[1]] == b[diff[0]]
        )
    s, l = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(s) and s[i] == l[i]:
        i += 1
    return s[i:] == l[i + 1 :]


def _strip_prefix(token: str, target: str) -> str | None:
    """Return the matching remainder if ``token`` is ``target`` with up to 2 prefix letters."""
    for n in (0, 1, 2):
        if (
            len(token) > n
            and all(c in PREFIXES for c in token[:n])
            and token[n:] == target
        ):
            return token[:n]
    return None


def _snippet(tokens: list[str], i: int, j: int, width: int = 4) -> str:
    return " ".join(tokens[max(0, i - width) : j + width])


def _match_sequence(
    tokens: list[str], pattern: list[str]
) -> tuple[int, int, float] | None:
    """Find ``pattern`` (list of tokens) in ``tokens``. Returns (start, end, confidence)."""
    n = len(pattern)
    best: tuple[int, int, float] | None = None
    for i in range(len(tokens) - n + 1):
        conf = 1.0
        ok = True
        for k, p in enumerate(pattern):
            tok = tokens[i + k]
            if tok == p:
                continue
            if k == 0 and _strip_prefix(tok, p) is not None:
                conf = min(conf, 0.94)
                continue
            long_enough = len(p) >= 5 and len(tok) >= 4
            if long_enough and _within_one_edit(tok, p):
                conf = min(conf, 0.7)
                continue
            if k == 0 and long_enough and len(tok) > 1 and _within_one_edit(tok[1:], p):
                conf = min(conf, 0.65)  # typo AND a prefix letter
                continue
            ok = False
            break
        if ok and (best is None or conf > best[2]):
            best = (i, i + n, conf)
    return best


_SEVERITY_CAP = {"low": 0.6, "medium": 0.8, "high": 0.95}
_KIND_LABEL = {
    "codename": "שם קוד",
    "site": "אתר/מיקום",
    "unit": "יחידה",
    "other": "מונח",
}
_LOCATION_CONTEXT = {
    "נמצא",
    "נמצאים",
    "בבסיס",
    "בבסיסי",
    "בעמדה",
    "בגזרה",
    "כרגע",
    "עכשיו",
    "מוצב",
    "מוצבים",
    "בדרך",
}


def match_terms(text: str, terms: list[TermSpec], source: str = "text") -> list[Hit]:
    if not text or not terms:
        return []
    variants = [(norm(text), 0.0)]
    flat = deobfuscate(text)
    if flat != _base_normalize(text).translate(_FINALS):
        variants.append(
            (norm(flat), 0.05)
        )  # penalty: matched only after de-obfuscation
    hits: dict[tuple[str, str], Hit] = {}
    for body, penalty in variants:
        tokens = body.split()
        tokset = set(tokens)
        for t in terms:
            for form in (t.term, *t.aliases):
                pattern = norm(form).split()
                if not pattern:
                    continue
                m = _match_sequence(tokens, pattern)
                if not m:
                    continue
                start, end, conf = m
                cap = _SEVERITY_CAP[t.severity]
                # short single-word terms are ambiguous in Hebrew ("נשר" = eagle): damp them
                ambiguity = 0.25 if len(pattern) == 1 and len(pattern[0]) <= 3 else 0.0
                boost = 0.05 if t.kind == "site" and tokset & _LOCATION_CONTEXT else 0.0
                score = round(
                    min(
                        0.99,
                        max(0.05, min(cap, 0.95 * conf - penalty - ambiguity)) + boost,
                    ),
                    3,
                )
                kind = "location" if t.kind == "site" else "codename"
                label = _KIND_LABEL[t.kind]
                how = "" if conf >= 0.94 else " (התאמה משוערת – ייתכן שגיאת כתיב)"
                if penalty:
                    how += " (הוסתר באמצעות סימנים בין אותיות)"
                key = f"{t.id}"
                if (key, kind) not in hits or hits[(key, kind)].score < score:
                    hits[(key, kind)] = Hit(
                        kind=kind,
                        severity=t.severity,
                        score=score,
                        reason=f"הטקסט מכיל {label} מרשימת המעקב{how}",
                        source=source,
                        snippet=_snippet(tokens, start, end),
                        term_id=t.id,
                        key=key,
                    )
                break  # one hit per term is enough
    return sorted(hits.values(), key=lambda h: -h.score)


# --- generic patterns (no watch-list needed) ------------------------------------------- #

_MARKERS = [
    (r"סודי ביותר|top secret", "high", 0.85, "סימון סיווג 'סודי ביותר'"),
    (
        r"(?<![א-ת])סודי(?![א-ת])|(?<![a-z])secret(?![a-z])",
        "high",
        0.7,
        "סימון סיווג 'סודי'",
    ),
    (
        r"(?<![א-ת])שמור(?![א-ת])|(?<![a-z])restricted(?![a-z])",
        "medium",
        0.55,
        "סימון סיווג 'שמור'",
    ),
    (r"בלמס|בלמ\"ס", "medium", 0.6, "סימון 'בלמ\"ס'"),
    (
        r"לשימוש פנימי|(?<![a-z])confidential(?![a-z])|classified",
        "medium",
        0.6,
        "סימון סיווג/הגבלת הפצה",
    ),
    (r"פקודת מבצע|פקמ|(?<![א-ת])נוהל קרב", "medium", 0.5, "הפניה למסמך מבצעי"),
]
_COORD = [
    (r"(?<!\d)[23]\d\.\d{3,}\s*[,;/ ]\s*[34]\d\.\d{3,}(?!\d)", "קואורדינטות גאוגרפיות"),
    (
        r"(?<!\d)\d{6}\s*[,;/ ]\s*\d{6,7}(?!\d)",
        "קואורדינטות רשת (נראות כרשת ישראל החדשה)",
    ),
    (
        r"(?:google\.[a-z.]+/maps|maps\.app\.goo\.gl|waze\.com/ul)\S*",
        "קישור למיקום במפה",
    ),
    (
        r"(?<![a-z])\d{1,2}[a-z]{3}\s?[a-z]{2}\s?\d{4,5}\s?\d{4,5}(?![a-z0-9])",
        "קואורדינטות בפורמט MGRS",
    ),
]


def pattern_hits(text: str, source: str = "text") -> list[Hit]:
    if not text:
        return []
    t = _base_normalize(text).translate(_FINALS)
    t = _QUOTES.sub("", t)
    out: list[Hit] = []
    for i, (rx, sev, score, label) in enumerate(_MARKERS):
        rx2 = rx.translate(_FINALS)  # final letters are unified in ``t`` as well
        m = re.search(rx2, t)
        if m and i == 1 and re.search(_MARKERS[0][0], t):
            continue  # "סודי ביותר" already reported; do not also report plain "סודי"
        if m:
            kind = "classified_document" if source == "ocr" else "text_pattern"
            out.append(
                Hit(
                    kind,
                    sev,
                    score if source != "ocr" else min(0.95, score + 0.1),
                    f"{label} מופיע ב{'טקסט שחולץ מהתמונה' if source == 'ocr' else 'טקסט הפוסט'}",
                    source,
                    _around(t, m),
                    None,
                    f"marker{i}",
                )
            )
    for i, (rx, label) in enumerate(_COORD):
        m = re.search(rx, t)
        if m:
            out.append(
                Hit(
                    "location",
                    "high",
                    0.8,
                    f"{label} ב{'תמונה' if source == 'ocr' else 'פוסט'}",
                    source,
                    _around(t, m),
                    None,
                    f"coord{i}",
                )
            )
    return out


def _around(text: str, m: re.Match, width: int = 30) -> str:
    return text[max(0, m.start() - width) : m.end() + width].strip()


def analyze_text(text: str, terms: list[TermSpec], source: str = "text") -> list[Hit]:
    return match_terms(text, terms, source) + pattern_hits(text, source)


_ = unicodedata
