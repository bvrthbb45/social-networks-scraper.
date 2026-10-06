import io
import zipfile
from datetime import timedelta

import pytest

from app.ingest import excel
from tests.xlsx_helpers import HEAD, TODAY, good_row, workbook


def parse(rows, head=None):
    return excel.parse_roster(workbook(rows, head))


def test_happy_path_and_normalisation():
    p = parse(
        [
            good_row(1),
            good_row(
                2, **{"חשבון": "https://www.instagram.com/Some.User/", "פלטפורמה": ""}
            ),
            good_row(3, **{"פלטפורמה": "טיקטוק", "סטטוס": "סגור"}),
        ]
    )
    assert [r.username for r in p.rows] == ["test_user_1", "some.user", "test_user_3"]
    assert [r.platform for r in p.rows] == ["instagram", "instagram", "tiktok"]
    assert p.rows[2].status == "closed" and not p.rejected


@pytest.mark.parametrize(
    "override,code",
    [
        ({"פלטפורמה": "whatsapp"}, "platform_not_allowed"),
        ({"פלטפורמה": "וואטסאפ"}, "platform_not_allowed"),
        ({"אסמכתת הסכמה": ""}, "no_consent"),
        ({"תוקף עד": TODAY - timedelta(days=1)}, "consent_not_in_force"),
        ({"תוקף מ": TODAY + timedelta(days=1)}, "consent_not_in_force"),
        ({"תאריך חתימה": TODAY + timedelta(days=5)}, "bad_consent_dates"),
        ({"תוקף עד": TODAY - timedelta(days=400)}, "bad_consent_dates"),
        ({"תאריך חתימה": None}, "bad_consent_dates"),
        ({"סטטוס": "אולי"}, "bad_status"),
        ({"חשבון": "=1+1"}, "bad_account"),
        ({"חשבון": "a b"}, "bad_account"),
        ({"מספר אישי": "12"}, "bad_identity"),
        ({"שם מלא": ""}, "bad_identity"),
    ],
)
def test_row_rejections_are_codes_with_line_numbers(override, code):
    p = parse([good_row(1, **override), good_row(2)])
    assert p.rejected == {code: [2]} and len(p.rows) == 1 and p.total == 2


def test_phone_columns_are_never_read():
    head = HEAD + ["טלפון נייד", "WhatsApp number"]
    rows = [
        good_row(1, **{"טלפון נייד": "0501234567", "WhatsApp number": "0529999999"})
    ]
    p = parse(rows, head)
    assert p.phone_columns_ignored == 2 and p.ignored_columns == 2
    assert "0501234567" not in repr(p) and "0529999999" not in repr(p)


def test_hebrew_and_english_headers_both_work():
    en = [
        "personal number",
        "full name",
        "platform",
        "username",
        "status",
        "consent ref",
        "signed_on",
        "valid_from",
        "valid_until",
    ]
    r = {
        en[0]: "7001234",
        en[1]: "x y",
        en[2]: "tiktok",
        en[3]: "abc",
        en[4]: "open",
        en[5]: "F1",
        en[6]: TODAY - timedelta(days=2),
        en[7]: TODAY - timedelta(days=2),
        en[8]: TODAY + timedelta(days=9),
    }
    assert len(excel.parse_roster(workbook([r], en)).rows) == 1


def test_missing_required_column_rejects_file():
    head = [h for h in HEAD if h != "אסמכתת הסכמה"]
    with pytest.raises(excel.FileRejected) as e:
        parse([good_row(1)], head)
    assert e.value.code.startswith("missing_columns:consent_ref")


def test_not_xlsx_and_garbage_rejected():
    for blob, code in [
        (b"hello", "not_xlsx"),
        (b"PK\x03\x04junk", "not_xlsx"),
        (b"", "not_xlsx"),
    ]:
        with pytest.raises(excel.FileRejected) as e:
            excel.parse_roster(blob)
        assert e.value.code == code


def _with_extra(data: bytes, name: str, payload: bytes = b"x") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(
        out, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for i in zin.infolist():
            zout.writestr(i, zin.read(i.filename))
        zout.writestr(name, payload)
    return out.getvalue()


def test_macros_external_links_and_zip_bombs_rejected():
    base = workbook([good_row(1)])
    for extra, code in [
        ("xl/vbaProject.bin", "macros_not_allowed"),
        ("xl/externalLinks/externalLink1.xml", "external_links_not_allowed"),
    ]:
        with pytest.raises(excel.FileRejected) as e:
            excel.parse_roster(_with_extra(base, extra))
        assert e.value.code == code
    bomb = _with_extra(base, "xl/media/big.bin", b"\0" * (60 * 1024 * 1024))
    assert len(bomb) < excel.MAX_BYTES  # tiny on the wire, huge when expanded
    with pytest.raises(excel.FileRejected) as e:
        excel.parse_roster(bomb)
    assert e.value.code == "file_too_large"


def test_oversize_and_row_limit(monkeypatch):
    with pytest.raises(excel.FileRejected) as e:
        excel.parse_roster(b"PK" + b"0" * (excel.MAX_BYTES + 1))
    assert e.value.code == "file_too_large"
    monkeypatch.setattr(excel, "MAX_ROWS", 3)
    with pytest.raises(excel.FileRejected) as e:
        parse([good_row(i) for i in range(1, 6)])
    assert e.value.code == "too_many_rows"


def test_blank_lines_skipped_and_formulas_never_evaluated():
    wb = workbook(
        [good_row(1), {}, good_row(2, **{"שם מלא": '=HYPERLINK("http://x")'})]
    )
    p = excel.parse_roster(wb)
    assert p.total == 2  # blank row ignored
    # a formula has no cached value (data_only), so it reads as empty and the row is refused
    assert p.rejected == {"bad_identity": [4]} and len(p.rows) == 1
