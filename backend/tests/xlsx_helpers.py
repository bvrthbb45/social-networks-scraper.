import io
from datetime import date, timedelta

from openpyxl import Workbook

TODAY = date.today()
HEAD = [
    "מספר אישי",
    "שם מלא",
    "יחידה",
    "פלטפורמה",
    "חשבון",
    "סטטוס",
    "אסמכתת הסכמה",
    "תאריך חתימה",
    "תוקף מ",
    "תוקף עד",
]


def good_row(n=1, **kw):
    r = {
        "מספר אישי": f"700{n:04d}",
        "שם מלא": f"חייל בדוי {n}",
        "יחידה": "יחידה א",
        "פלטפורמה": "instagram",
        "חשבון": f"@test_user_{n}",
        "סטטוס": "פתוח",
        "אסמכתת הסכמה": f"FORM-{n}",
        "תאריך חתימה": TODAY - timedelta(days=30),
        "תוקף מ": TODAY - timedelta(days=30),
        "תוקף עד": TODAY + timedelta(days=300),
    }
    r.update(kw)
    return r


def workbook(rows, head=None) -> bytes:
    head = head or HEAD
    wb = Workbook()
    ws = wb.active
    ws.append(head)
    for r in rows:
        ws.append([r.get(h) for h in head])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def terms_workbook(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["מונח", "כינויים", "סוג", "חומרה"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
