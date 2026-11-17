from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.core.database import utcnow
from app.core.deps import DB, Operator
from app.models import ExportHistory
from app.repositories.base import paginate
from app.controllers.statistics import F
from app.services import export_service
from app.services.export_service import REPORTS

router = APIRouter(prefix="/exports", tags=["Exports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/excel")
def excel(db: DB, user: Operator, f: F, report: str = Query("full", json_schema_extra={"enum": list(REPORTS)})):
    data, n = export_service.build_workbook(db, report, f, user)
    name = f"bao_cao_{report}_{utcnow():%Y%m%d_%H%M}.xlsx"
    export_service.record(db, user, report, "xlsx", f, name, n)
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/csv")
def csv_export(db: DB, user: Operator, f: F, kind: Literal["rainfall", "water_level"] = "rainfall"):
    data, n = export_service.build_csv(db, kind, f)
    name = f"{kind}_{utcnow():%Y%m%d_%H%M}.csv"
    export_service.record(db, user, kind, "csv", f, name, n)
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/history")
def history(db: DB, user: Operator, page: int = Query(1, ge=1), size: int = Query(20, le=100)):
    from sqlalchemy import select

    stmt = select(ExportHistory)
    if "ADMIN" not in user.role_codes:
        stmt = stmt.where(ExportHistory.user_id == user.id)
    rows, total = paginate(db, stmt, page, size, ExportHistory.created_at, "desc")
    return {"items": [{"id": r.id, "report_type": r.report_type, "file_format": r.file_format,
                       "file_name": r.file_name, "row_count": r.row_count, "filters": r.filters,
                       "created_at": r.created_at.isoformat() + "Z"} for r in rows], "total": total}
