"""Test-only helpers for the end-to-end run (synthetic data, never real people)."""
import sys
from datetime import date, datetime, timedelta, timezone

import pyotp


def totp(secret: str, offset: int = 0) -> str:
    return pyotp.TOTP(secret).at(datetime.now(timezone.utc) + timedelta(seconds=30 * offset))


def roster(path: str) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["מספר אישי", "שם מלא", "יחידה", "פלטפורמה", "חשבון", "סטטוס", "אסמכתת הסכמה", "תאריך חתימה", "תוקף מ", "תוקף עד", "טלפון"])
    d = date.today()
    ok = ["7000001", "חייל בדוי", "יחידה א", "instagram", "@e2e_user", "פתוח", "FORM-1", d - timedelta(days=9), d - timedelta(days=9), d + timedelta(days=300), "0500000000"]
    bad = ["7000002", "חייל בדוי ב", "יחידה א", "whatsapp", "@x", "פתוח", "FORM-2", d, d, d + timedelta(days=9), "0500000001"]
    closed = ["7000003", "חייל בדוי ג", "יחידה ב", "tiktok", "e2e_closed", "סגור", "FORM-3", d - timedelta(days=9), d - timedelta(days=9), d + timedelta(days=300), ""]
    for r in (ok, bad, closed):
        ws.append(r)
    wb.save(path)


def terms(path: str) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["מונח", "כינויים", "סוג", "חומרה"])
    ws.append(["נשר שחור", "", "שם קוד", "גבוהה"])
    ws.append(["בסיס צפוני", "", "אתר", "גבוהה"])
    wb.save(path)


def seed() -> None:
    import io

    from PIL import Image

    from app.analysis import pipeline
    from app.database import SessionLocal
    from app.ingest import posts as intake

    im = Image.new("RGB", (200, 300), (120, 120, 120))
    im.paste((85, 107, 47), (80, 60, 140, 200))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    import base64

    with SessionLocal() as db:
        acct, _ = intake.find_account(db, "instagram", "e2e_user")
        p = intake.add_post(db, acct, {"text": "אנחנו כרגע בבסיס צפוני. מסמך סודי", "url": "https://example.org/p/1", "images": [base64.b64encode(buf.getvalue()).decode()]})
        pipeline.analyze_post(db, p, pipeline.load_terms(db))
        db.commit()


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    out = globals()[cmd](*args)
    if out is not None:
        print(out)
