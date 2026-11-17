from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, File, Query, Request, UploadFile
from sqlalchemy import select

from app.core.database import utcnow
from app.core.deps import DB, Operator, OptionalUser
from app.core.errors import AppError
from app.models import DataSource
from app.repositories import observations as obs_repo
from app.schemas.common import Page, to_utc_naive
from app.schemas.views import ImportReport, ObservationIn, ObservationOut, StationCreate, StationOut, StationUpdate
from app.services import forecast_service, observation_service, station_service
from app.services.audit_service import audit

router = APIRouter(prefix="/stations", tags=["Stations"])


@router.get("", response_model=Page[StationOut])
def list_stations(db: DB, q: str | None = None, station_type: str | None = None, status: str | None = None,
                  area_id: int | None = None, connection: Literal["ONLINE", "OFFLINE", "NO_DATA"] | None = None,
                  page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200), sort: str = "code",
                  direction: Literal["asc", "desc"] = "asc"):
    items, total = station_service.list_stations(db, q, station_type, status, area_id, connection, page, size,
                                                 sort, direction)
    return Page(items=items, total=total, page=page, size=size)


@router.post("", response_model=StationOut, status_code=201)
def create_station(body: StationCreate, user: Operator, request: Request, db: DB):
    return station_service.to_out(station_service.create(db, body, user, request))


@router.post("/import", response_model=ImportReport)
async def import_any(user: Operator, request: Request, db: DB, file: UploadFile = File(...)):
    """CSV/XLSX với cột station_code, observed_at, rainfall_mm, water_level_cm|water_level_m."""
    return await _import(db, None, file, user, request)


@router.get("/{sid}", response_model=StationOut)
def get_station(sid: int, db: DB):
    st = station_service.get(db, sid)
    return station_service.to_out(st, obs_repo.latest_values(db, [sid]).get(sid))


@router.patch("/{sid}", response_model=StationOut)
def update_station(sid: int, body: StationUpdate, user: Operator, request: Request, db: DB):
    return station_service.to_out(station_service.update(db, sid, body, user, request))


@router.delete("/{sid}", status_code=204)
def delete_station(sid: int, user: Operator, request: Request, db: DB):
    station_service.soft_delete(db, sid, user, request)


@router.get("/{sid}/observations", response_model=list[ObservationOut])
def observations(sid: int, db: DB, date_from: datetime | None = None, date_to: datetime | None = None):
    station_service.get(db, sid)
    end = to_utc_naive(date_to) if date_to else utcnow()
    start = to_utc_naive(date_from) if date_from else end - timedelta(hours=48)
    if end - start > timedelta(days=93):
        raise AppError(422, "RANGE_TOO_LARGE", "Khoảng thời gian tối đa 93 ngày")
    df = obs_repo.series(db, sid, start, end)
    return [ObservationOut(observed_at=r.time, rainfall_mm=_nan(r.rain_mm), water_level_cm=_nan(r.water_level_cm),
                           rain_quality=_nan(r.rain_q), wl_quality=_nan(r.wl_q), is_simulated=bool(r.sim))
            for r in df.itertuples()]


def _nan(v):
    return None if v is None or v != v else v


@router.post("/{sid}/observations", response_model=ImportReport, status_code=201)
def add_observation(sid: int, body: ObservationIn, user: Operator, request: Request, db: DB):
    st = station_service.get(db, sid)
    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    rep = observation_service.import_observations(db, [{
        "observed_at": to_utc_naive(body.observed_at).isoformat() + "+00:00",
        "rainfall_mm": body.rainfall_mm, "water_level_cm": body.water_level_cm}], st, src.id)
    audit(db, user, "OBSERVATION_MANUAL", "station", sid, body.model_dump(mode="json"), request)
    db.commit()
    return rep


@router.post("/{sid}/observations/import", response_model=ImportReport)
async def import_station(sid: int, user: Operator, request: Request, db: DB, file: UploadFile = File(...)):
    return await _import(db, station_service.get(db, sid), file, user, request)


async def _import(db, station, file: UploadFile, user, request):
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise AppError(413, "TOO_LARGE", "Tệp tối đa 10 MB")
    try:
        rows = observation_service.parse_table(file.filename or "", content)
        src = db.scalar(select(DataSource).where(DataSource.code == "IMPORT"))
        rep = observation_service.import_observations(db, rows, station, src.id)
    except (ValueError, KeyError, StopIteration) as e:
        raise AppError(422, "IMPORT_ERROR", f"Không đọc được tệp: {e}") from e
    audit(db, user, "OBSERVATION_IMPORT", "station", station.id if station else "",
          {k: v for k, v in rep.items() if k != "errors"} | {"file": (file.filename or "")[:100]}, request)
    db.commit()
    return rep


@router.get("/{sid}/quality")
def quality(sid: int, db: DB, _: Operator, days: int = Query(7, ge=1, le=90)):
    return station_service.quality_summary(db, sid, days)


@router.get("/{sid}/forecast")
def station_forecast(sid: int, db: DB, user: OptionalUser):
    st = station_service.get(db, sid)
    rows = forecast_service.station_forecast(db, sid)
    return {"station_id": sid, "station_code": st.code,
            "issued_at": rows[0].issued_at.isoformat() + "Z" if rows else None,
            "is_simulated": st.source.is_simulated,
            "points": [{"horizon_h": f.horizon_h, "target_time": f.target_time.isoformat() + "Z",
                        "rainfall_mm": f.rainfall_mm, "water_level_cm": f.water_level_cm,
                        "flood_probability": f.flood_probability, "data_quality": f.data_quality,
                        "is_cold_start": f.is_cold_start} for f in rows]}
