from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError, NotFound
from app.core.spatial import point_wkt, valid_hcm_coordinate
from app.models import (
    DataSource,
    MonitoringStation,
    RainfallObservation,
    Sensor,
    User,
    WaterLevelObservation,
)
from app.repositories import observations as obs_repo
from app.repositories.base import contains, paginate
from app.schemas.views import StationCreate, StationOut, StationUpdate
from app.services import gis_service
from app.services.audit_service import audit


def connection_status(st: MonitoringStation) -> str:
    if not st.last_observation_at:
        return "NO_DATA"
    age = utcnow() - st.last_observation_at
    return "ONLINE" if age <= timedelta(minutes=2 * st.interval_minutes + 15) else "OFFLINE"


def data_status(st: MonitoringStation) -> str:
    if not st.last_observation_at:
        return "UNAVAILABLE"
    if st.source.is_simulated:
        return "DEMO"
    return "LIVE" if connection_status(st) == "ONLINE" else "STALE"


def to_out(st: MonitoringStation, latest: dict | None = None) -> StationOut:
    o = StationOut.model_validate(st)
    o.connection_status = connection_status(st)
    o.data_status = data_status(st)
    if latest:
        o.latest_rainfall_mm = latest.get("rain")
        o.latest_water_level_cm = latest.get("wl")
    return o


def get(db: Session, sid: int) -> MonitoringStation:
    st = db.get(MonitoringStation, sid)
    if not st or st.deleted_at:
        raise NotFound("Trạm")
    return st


def list_stations(db: Session, q: str | None, station_type: str | None, status: str | None, area_id: int | None,
                  connection: str | None, page: int, size: int, sort: str, direction: str):
    stmt = select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None))
    if q:
        stmt = stmt.where(or_(contains(MonitoringStation.name, q), contains(MonitoringStation.code, q),
                              contains(MonitoringStation.address, q)))
    if station_type:
        stmt = stmt.where(MonitoringStation.station_type == station_type)
    if status:
        stmt = stmt.where(MonitoringStation.status == status)
    if area_id:
        stmt = stmt.where(MonitoringStation.area_id == area_id)
    sort_col = {"code": MonitoringStation.code, "name": MonitoringStation.name,
                "updated_at": MonitoringStation.updated_at,
                "last_observation_at": MonitoringStation.last_observation_at}.get(sort, MonitoringStation.code)
    if connection:  # trạng thái kết nối là giá trị tính toán -> lọc sau truy vấn
        rows = [s for s in db.scalars(stmt.order_by(sort_col)).unique() if connection_status(s) == connection]
        total, rows = len(rows), rows[(page - 1) * size: page * size]
    else:
        rows, total = paginate(db, stmt, page, size, sort_col, direction)
    latest = obs_repo.latest_values(db, [r.id for r in rows])
    return [to_out(r, latest.get(r.id)) for r in rows], total


def _source(db: Session, code: str) -> DataSource:
    src = db.scalar(select(DataSource).where(DataSource.code == code))
    if not src:
        raise AppError(422, "INVALID_SOURCE", f"Nguồn dữ liệu {code} không tồn tại")
    return src


def create(db: Session, data: StationCreate, user: User, request=None) -> MonitoringStation:
    if not valid_hcm_coordinate(data.latitude, data.longitude):
        raise AppError(422, "OUT_OF_AREA", "Toạ độ nằm ngoài phạm vi TP.HCM")
    if db.scalar(select(MonitoringStation.id).where(MonitoringStation.code == data.code)):
        raise AppError(409, "DUPLICATE", f"Mã trạm {data.code} đã tồn tại")
    area = gis_service.nearest_area(db, data.longitude, data.latitude, level="DISTRICT")
    st = MonitoringStation(**data.model_dump(exclude={"source_code"}), source_id=_source(db, data.source_code).id,
                           area_id=area.id if area else None, location=point_wkt(data.longitude, data.latitude))
    db.add(st)
    db.flush()
    for t, unit in (("RAIN_GAUGE", "mm"), ("WATER_LEVEL", "cm")):
        if data.station_type == "COMBINED" or (t == "RAIN_GAUGE") == (data.station_type == "RAIN"):
            db.add(Sensor(station_id=st.id, sensor_type=t, unit=unit))
    audit(db, user, "STATION_CREATE", "station", st.id, {"code": st.code}, request)
    db.commit()
    return st


def update(db: Session, sid: int, data: StationUpdate, user: User, request=None) -> MonitoringStation:
    st = get(db, sid)
    changes = data.model_dump(exclude_unset=True)
    lat, lon = changes.get("latitude", st.latitude), changes.get("longitude", st.longitude)
    if not valid_hcm_coordinate(lat, lon):
        raise AppError(422, "OUT_OF_AREA", "Toạ độ nằm ngoài phạm vi TP.HCM")
    before = {k: getattr(st, k) for k in changes}
    for k, v in changes.items():
        setattr(st, k, v)
    if "latitude" in changes or "longitude" in changes:
        st.location = point_wkt(lon, lat)
        area = gis_service.nearest_area(db, lon, lat, level="DISTRICT")
        st.area_id = area.id if area else None
    audit(db, user, "STATION_UPDATE", "station", st.id, {"before": before, "after": changes}, request)
    db.commit()
    db.refresh(st)
    return st


def soft_delete(db: Session, sid: int, user: User, request=None) -> None:
    st = get(db, sid)
    st.deleted_at = utcnow()
    st.status = "INACTIVE"
    st.code = f"{st.code}~{st.id}"[:30]  # giải phóng mã để có thể tạo lại; bản ghi lịch sử giữ nguyên
    audit(db, user, "STATION_DELETE", "station", st.id, None, request)
    db.commit()


def quality_summary(db: Session, sid: int, days: int = 7) -> dict:
    since = utcnow() - timedelta(days=days)
    out = {}
    for name, model in (("rainfall", RainfallObservation), ("water_level", WaterLevelObservation)):
        rows = dict(db.execute(select(model.quality_flag, func.count()).where(
            model.station_id == sid, model.observed_at >= since).group_by(model.quality_flag)).all())
        out[name] = rows
    st = get(db, sid)
    expected = days * 24 * 60 // st.interval_minutes
    received = sum(out["water_level"].values()) or sum(out["rainfall"].values())
    out["expected_records"] = expected
    out["completeness"] = round(min(received / expected, 1.0), 4) if expected else None
    out["delay_minutes"] = (round((utcnow() - st.last_observation_at).total_seconds() / 60, 1)
                            if st.last_observation_at else None)
    return out
