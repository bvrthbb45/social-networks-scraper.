import pytest

from app.analysis.text import (
    TermSpec,
    analyze_text,
    deobfuscate,
    match_terms,
    norm,
    pattern_hits,
)

T = [
    TermSpec("t1", "נשר שחור", ("הנשר",), "codename", "high"),
    TermSpec("t2", "בסיס צפוני", (), "site", "high"),
    TermSpec("t3", "נשר", (), "codename", "medium"),
    TermSpec("t4", "Black Eagle", (), "unit", "medium"),
]


def ids(text, terms=T):
    return {h.term_id: h for h in match_terms(text, terms)}


def test_exact_and_prefixed_hebrew():
    assert "t1" in ids("הגענו אל נשר שחור")
    assert "t1" in ids("היינו ב נשר שחור")  # separate preposition
    assert "t2" in ids("אתמול בבסיס צפוני היה קר")  # ב + בסיס
    assert "t2" in ids("הלכנו לבסיס צפוני")  # ל prefix
    assert "t2" in ids("וכשהגענו לבסיס צפוני")


def test_niqqud_final_letters_quotes_and_case():
    assert "t4" in ids("BLACK EAGLE rocks")
    assert "t3" in ids("נֶשֶׁר")  # niqqud
    assert "t2" in ids("בסיס צפוניִ")
    spec = [TermSpec("q", 'בלמ"ס', (), "other", "low")]
    assert "q" in ids("בלמס", spec) and "q" in ids('בלמ"ס', spec)


def test_typos_only_on_long_terms():
    assert "t4" in ids("black egle")  # 1 deletion
    assert "t2" in ids("בסיס צפונים")  # substitution/insertion
    assert "t3" not in ids("נסר")  # 3-letter term: no fuzzy matching (too ambiguous)
    assert ids("black egle")["t4"].score < ids("black eagle")["t4"].score


def test_obfuscation_is_caught_with_a_penalty():
    assert "t1" in ids("נ.ש.ר ש.ח.ו.ר")
    assert "t3" in ids("נ ש ר")
    assert ids("נ.ש.ר")["t3"].score < ids("נשר")["t3"].score


def test_no_false_hits_on_unrelated_text():
    assert match_terms("יום יפה בים עם המשפחה", T) == []
    assert match_terms("", T) == [] and match_terms("x", []) == []
    assert "t1" not in ids("נשרים שחורים")  # different words, not a typo of the phrase


def test_short_ambiguous_terms_are_damped_and_severity_caps_score():
    short = ids("ראיתי נשר בשמיים")["t3"]
    long = ids("ראיתי נשר שחור בשמיים")["t1"]
    assert short.score < long.score and short.score <= 0.8 and long.score <= 0.95


def test_site_with_location_context_scores_higher():
    spec = [
        TermSpec("s", "בסיס צפוני", (), "site", "medium")
    ]  # medium: below the score cap
    a = ids("אנחנו כרגע בבסיס צפוני", spec)["s"].score
    b = ids("סיפור על בסיס צפוני", spec)["s"].score
    assert a > b


def test_hit_shape_is_a_lead_with_hebrew_reason():
    h = ids("נשר שחור")["t1"]
    assert h.kind == "codename" and h.source == "text" and "רשימת המעקב" in h.reason
    assert h.snippet and 0 < h.score <= 1
    assert ids("בסיס צפוני")["t2"].kind == "location"


def test_classification_markers_and_coordinates():
    kinds = lambda s, src="text": {
        (h.kind, h.key) for h in pattern_hits(s, src)
    }  # noqa: E731
    assert ("text_pattern", "marker0") in kinds("המסמך סודי ביותר")
    assert ("text_pattern", "marker1") in kinds("מסמך סודי")
    assert ("text_pattern", "marker1") not in kinds("סודי ביותר")  # reported once
    assert ("text_pattern", "marker3") in kinds('בלמ"ס')
    assert any(k == "location" for k, _ in kinds("32.0853, 34.7818"))
    assert any(k == "location" for k, _ in kinds("https://maps.app.goo.gl/abc123"))
    assert any(k == "location" for k, _ in kinds("מיקום 178500 662300"))
    assert pattern_hits("שלום, מה שלומך? קבעתי ל-12:30", "text") == []
    assert pattern_hits("סודי", "text")[0].kind == "text_pattern"
    assert (
        pattern_hits("סודי", "ocr")[0].kind == "classified_document"
    )  # found inside a picture


@pytest.mark.parametrize("word", ["סודית", "מסודר", "שמורות", "הסודיות"])
def test_marker_words_need_word_boundaries(word):
    assert [
        h for h in pattern_hits(f"זה {word} מאוד") if h.key in ("marker1", "marker2")
    ] == []


def test_deobfuscate_leaves_normal_text_alone():
    assert norm(deobfuscate("שלום עולם")) == norm("שלום עולם")
    assert deobfuscate("a b c") == "abc"
    assert deobfuscate("hello world") == "hello world"


def test_analyze_text_combines_both():
    kinds = {h.kind for h in analyze_text("בבסיס צפוני סודי 32.0853, 34.7818", T)}
    assert {"location", "text_pattern"} <= kinds
