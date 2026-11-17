from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.core.database import utcnow
from app.core.deps import DB, Operator
from app.core.errors import AppError
from app.schemas.common import to_utc_naive
from app.services import statistics_service as stats
from app.services.statistics_service import Filters

router = APIRouter(prefix="/statistics", tags=["Statistics"])
Group = Literal["hour", "day", "month", "year"]


def filters(date_from: datetime | None = None, date_to: datetime | None = None, area_id: int | None = None,
            station_id: int | None = None, risk_level: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
            data_type: Literal["SIMULATED", "REAL"] | None = None) -> Filters:
    """Khoảng thời gian [date_from, date_to). Mặc định 7 ngày gần nhất."""
    end = to_utc_naive(date_to) if date_to else utcnow()
    start = to_utc_naive(date_from) if date_from else end - timedelta(days=7)
    if start >= end:
        raise AppError(422, "INVALID_RANGE", "date_from phải trước date_to")
    if end - start > timedelta(days=3700):
        raise AppError(422, "RANGE_TOO_LARGE", "Khoảng thời gian quá lớn")
    return Filters(start, end, area_id, station_id, risk_level, data_type)


F = Annotated[Filters, Depends(filters)]


@router.get("/overview")
def overview(db: DB, _: Operator, f: F):
    return stats.overview(db, f)


@router.get("/rainfall")
def rainfall(db: DB, _: Operator, f: F, group: Group = "day"):
    return {"series": stats.obs_series(db, f, "rainfall", group), "by_station": stats.by_station(db, f, "rainfall"),
            "unit": "mm"}


@router.get("/water-level")
def water_level(db: DB, _: Operator, f: F, group: Group = "day"):
    return {"series": stats.obs_series(db, f, "water", group), "by_station": stats.by_station(db, f, "water"),
            "unit": "cm"}


@router.get("/observations")
def observation_table(db: DB, _: Operator, f: F, kind: Literal["rainfall", "water_level"] = "rainfall",
                      page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500)):
    """Bảng dữ liệu chi tiết có phân trang (mới nhất trước)."""
    rows, total = stats.obs_page(db, f, kind, page, size)
    return {"items": [{"observed_at": r[0], "station_code": r[1], "station_name": r[2], "area": r[3],
                       "value": r[4], "quality": r[5], "is_simulated": r[6]} for r in rows],
            "page": page, "size": size, "total": total}


@router.get("/alerts")
def alerts(db: DB, _: Operator, f: F, group: Group = "day"):
    return stats.alert_stats(db, f, group)


@router.get("/risk")
def risk(db: DB, _: Operator, f: F, group: Group = "day"):
    return {"trend": stats.risk_trend(db, f, group), "current": stats.latest_risk_counts(db)}


@router.get("/flood-events")
def flood_events(db: DB, _: Operator, f: F, group: Group = "month"):
    return stats.flood_event_stats(db, f, group)


@router.get("/model-performance")
def model_performance(db: DB, _: Operator, f: F):
    return stats.model_performance(db, f)


@router.get("/data-quality")
def data_quality(db: DB, _: Operator, f: F):
    return stats.data_quality(db, f)


@router.get("/stations")
def stations(db: DB, _: Operator):
    return stats.station_status(db)


@router.get("/cameras")
def cameras(db: DB, _: Operator, f: F):
    return stats.camera_status(db, f)


@router.get("/alert-handling")
def alert_handling(db: DB, _: Operator, f: F):
    return stats.alert_handling(db, f)
