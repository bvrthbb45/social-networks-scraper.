from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..deps import require_roles
from ..ingest import excel, service
from ..limiter import limiter
from ..models import Import, User

router = APIRouter(prefix="/imports", tags=["imports"])
_MAX_LINES_SHOWN = 200


async def _read(upload: UploadFile) -> bytes:
    data = await upload.read(excel.MAX_BYTES + 1)
    if len(data) > excel.MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large")
    return data


def _summary(
    res: service.Result,
    parsed: excel.Parsed,
    dry_run: bool,
    imp: Import | None,
    dup: bool,
) -> dict:
    return {
        "dry_run": dry_run,
        "import_id": str(imp.id) if imp and not dry_run else None,
        "duplicate_file": dup,
        "rows_total": parsed.total,
        "soldiers_created": res.soldiers_created,
        "accounts_created": res.accounts_created,
        "accounts_updated": res.accounts_updated,
        "unchanged": res.unchanged,
        "rejected": {
            k: v[:_MAX_LINES_SHOWN] for k, v in res.rejected.items()
        },  # reason -> line numbers
        "unused_columns": parsed.ignored_columns,
        "phone_columns_ignored": parsed.phone_columns_ignored,
    }


@router.post("/roster")
@limiter.limit("10/minute")
async def import_roster(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(default=True),  # safe default: preview first
    user: User = Depends(require_roles("uploader", "admin")),
    db: Session = Depends(get_db),
) -> dict:
    data = await _read(file)
    try:
        parsed = excel.parse_roster(data)
    except excel.FileRejected as e:
        audit.record(
            db,
            "import.rejected",
            request,
            user.id,
            details={"reason": e.code.split(":")[0]},
        )
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.code)
    import hashlib

    dup = (
        db.scalar(
            select(Import.id).where(Import.sha256 == hashlib.sha256(data).hexdigest())
        )
        is not None
    )
    imp, res = service.apply_roster(db, parsed, file.filename or "", data, user.id)
    summary = _summary(res, parsed, dry_run, imp, dup)
    if dry_run:
        db.rollback()  # nothing is kept from a preview
        audit.record(
            db, "import.previewed", request, user.id, details={"rows": parsed.total}
        )
    else:
        audit.record(
            db,
            "import.committed",
            request,
            user.id,
            object_type="import",
            object_id=imp.id,
            details={
                k: summary[k]
                for k in (
                    "rows_total",
                    "soldiers_created",
                    "accounts_created",
                    "accounts_updated",
                )
            },
        )
    db.commit()
    return summary


@router.get("")
def list_imports(
    user: User = Depends(require_roles("uploader", "admin", "auditor")),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.scalars(
        select(Import).order_by(Import.uploaded_at.desc()).limit(100)
    ).all()
    return [
        {
            "id": str(i.id),
            "filename": i.filename,
            "status": i.status,
            "rows_total": i.rows_total,
            "rows_accepted": i.rows_accepted,
            "rows_rejected": i.rows_rejected,
            "reject_reasons": i.reject_reasons,
            "uploaded_at": i.uploaded_at.isoformat(),
        }
        for i in rows
    ]
