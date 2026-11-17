import hashlib
import json

from fastapi import APIRouter, File, Query, Request, UploadFile
from sqlalchemy import func, select

from app.core.deps import DB, Admin, OptionalUser, explanation_for, is_staff
from app.core.errors import AppError, NotFound
from app.core.spatial import valid_hcm_coordinate
from app.gis.importer import import_geojson
from app.models import (
    AdministrativeArea,
    Alert,
    Camera,
    DataSource,
    FloodRiskSnapshot,
    Forecast,
    HistoricalFloodEvent,
    MonitoringStation,
)
from app.repositories import observations as obs_repo
from app.schemas.views import AreaOut
from app.services import camera_service, gis_service, station_service, traffic_camera_service
from app.services.audit_service import audit

router = APIRouter(prefix="/gis", tags=["GIS"])


def _pt(lon, lat, props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


@router.get("/areas", response_model=list[AreaOut])
def areas(db: DB, level: str = Query("DISTRICT", pattern="^(DISTRICT|WARD)$"), parent_id: int | None = None):
    stmt = select(AdministrativeArea).where(AdministrativeArea.level == level)
    if parent_id:
        stmt = stmt.where(AdministrativeArea.parent_id == parent_id)
    return list(db.scalars(stmt.order_by(AdministrativeArea.name)))


@router.get("/geojson")
def boundaries(db: DB):
    """Ranh giới hành chính (GeoJSON, lon/lat, WGS84)."""
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": aid, "geometry": a["geom"],
         "properties": {"id": aid, "code": a["code"], "name": a["name"], "level": a["level"]}}
        for aid, a in gis_service.area_geometries(db).items()],
        "attribution": "Ranh giới: geoBoundaries (OCHA ROAP), CC BY 3.0 IGO — ranh giới quận/huyện năm 2020"}


@router.get("/risk-layers")
def risk_layers(db: DB, horizon: int = Query(0, ge=0, le=6)):
    return gis_service.risk_geojson(db, horizon)


@router.get("/features")
def features(db: DB, user: OptionalUser, horizon: int = Query(0, ge=0, le=6)):
    """Lớp điểm: trạm (mưa/mực nước), camera, điểm ngập lịch sử, cảnh báo đang hoạt động."""
    staff = is_staff(user)
    stations = list(db.scalars(select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None))))
    latest = obs_repo.latest_values(db, [s.id for s in stations])
    issued = db.scalar(select(func.max(Forecast.issued_at)))
    fc = {}
    if issued and horizon:
        fc = {f.station_id: f for f in db.scalars(select(Forecast).where(
            Forecast.issued_at == issued, Forecast.horizon_h == horizon))}
    st_feats = []
    for s in stations:
        lv, f = latest.get(s.id, {}), fc.get(s.id)
        st_feats.append(_pt(s.longitude, s.latitude, {
            "id": s.id, "code": s.code, "name": s.name, "station_type": s.station_type, "status": s.status,
            "connection": station_service.connection_status(s), "data_status": station_service.data_status(s),
            "rainfall_mm": f.rainfall_mm if f else lv.get("rain"),
            "water_level_cm": f.water_level_cm if f else lv.get("wl"),
            "flood_probability": f.flood_probability if f else None,
            "ratio": ((f.water_level_cm if f else lv.get("wl")) or 0) / s.flood_threshold_cm,
            "threshold_cm": s.flood_threshold_cm, "is_forecast": bool(f)}))
    # camera giao thông có lớp riêng (/gis/traffic-cameras): ~800 camera, không cần tra phát hiện YOLO
    cams = select(Camera).where(Camera.deleted_at.is_(None), Camera.code.not_like(traffic_camera_service.CODE_PREFIX + "%"))
    if not staff:
        cams = cams.where(Camera.is_public.is_(True))
    cam_feats = []
    for c in db.scalars(cams):
        d = camera_service.latest_detection(db, c.id)
        cam_feats.append(_pt(c.longitude, c.latitude, {
            "id": c.id, "code": c.code, "name": c.name, "status": c.status, "is_simulated": c.source.is_simulated,
            "flood_ratio": d.flood_ratio if d else None, "method": d.method if d else None}))
    ev = db.execute(select(HistoricalFloodEvent.location_name, HistoricalFloodEvent.longitude,
                           HistoricalFloodEvent.latitude, func.count(), func.max(HistoricalFloodEvent.max_depth_cm),
                           func.max(HistoricalFloodEvent.started_at), func.bool_or(HistoricalFloodEvent.is_simulated))
                    .group_by(HistoricalFloodEvent.location_name, HistoricalFloodEvent.longitude,
                              HistoricalFloodEvent.latitude)).all()
    ev_feats = [_pt(r[1], r[2], {"name": r[0], "count": r[3], "max_depth_cm": r[4],
                                 "last_at": r[5].isoformat() + "Z", "is_simulated": bool(r[6])}) for r in ev]
    al = select(Alert).where(Alert.status.in_(["NEW", "ACKNOWLEDGED", "IN_PROGRESS"]))
    if not staff:
        al = al.where(Alert.is_public.is_(True))
    al_feats = [_pt(a.area.centroid_lon, a.area.centroid_lat, {
        "id": a.id, "code": a.code, "risk_level": a.risk_level, "title": a.title,
        "status": a.status if staff else "NEW",
        "triggered_at": a.triggered_at.isoformat() + "Z", "is_simulated": a.is_simulated}) for a in db.scalars(al)]
    fcoll = lambda f: {"type": "FeatureCollection", "features": f}  # noqa: E731
    return {"stations": fcoll(st_feats), "cameras": fcoll(cam_feats), "flood_events": fcoll(ev_feats),
            "alerts": fcoll(al_feats), "horizon_h": horizon,
            "forecast_issued_at": issued.isoformat() + "Z" if issued else None}


@router.get("/identify")
def identify(db: DB, user: OptionalUser, lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    """Thông tin tại điểm click: khu vực, trạm gần nhất, rủi ro 0–6h, lịch sử ngập, camera."""
    if not valid_hcm_coordinate(lat, lon):
        raise AppError(422, "OUT_OF_AREA", "Điểm nằm ngoài phạm vi TP.HCM")
    area = gis_service.area_at(db, lon, lat)
    near = gis_service.nearest_stations(db, lon, lat, 3, 10000)
    latest = obs_repo.latest_values(db, [sid for sid, _ in near])
    st_info = []
    for sid, dist in near:
        s = db.get(MonitoringStation, sid)
        st_info.append({"id": s.id, "code": s.code, "name": s.name, "distance_m": round(dist),
                        "rainfall_mm": latest.get(sid, {}).get("rain"), "water_level_cm": latest.get(sid, {}).get("wl"),
                        "observed_at": (latest.get(sid, {}).get("wl_at") or latest.get(sid, {}).get("rain_at")),
                        "data_status": station_service.data_status(s), "source": s.source.name})
    risk = []
    if area:
        issued = gis_service.latest_issue_time(db)
        risk = [{"horizon_h": r.horizon_h, "risk_level": r.risk_level, "score": r.score,
                 "flood_probability": r.flood_probability, "rainfall_mm": r.rainfall_mm,
                 "explanation": explanation_for(r.explanation, user)} for r in db.scalars(select(FloodRiskSnapshot).where(
                     FloodRiskSnapshot.area_id == area.id, FloodRiskSnapshot.issued_at == issued)
                     .order_by(FloodRiskSnapshot.horizon_h))]
    hist = db.execute(select(func.count(), func.max(HistoricalFloodEvent.started_at),
                             func.max(HistoricalFloodEvent.max_depth_cm))
                      .where(func.ST_DistanceSphere(HistoricalFloodEvent.__table__.c.location,
                                                    func.ST_GeomFromText(f"POINT({lon} {lat})", 4326)) <= 1500)).one()
    parent = db.get(AdministrativeArea, area.parent_id) if area and area.parent_id else None
    return {"lat": lat, "lon": lon, "area": AreaOut.model_validate(area).model_dump() if area else None,
            "district": parent.name if parent else None,
            "stations": st_info, "risk": risk,
            "history": {"events_within_1500m": hist[0], "last_event_at": hist[1], "max_depth_cm": hist[2]},
            "issued_at": gis_service.latest_issue_time(db)}


@router.get("/areas/{aid}")
def area_detail(aid: int, db: DB, user: OptionalUser):
    a = db.get(AdministrativeArea, aid)
    if not a:
        raise NotFound("Khu vực")
    issued = gis_service.latest_issue_time(db)
    snaps = list(db.scalars(select(FloodRiskSnapshot).where(FloodRiskSnapshot.area_id == aid,
                                                            FloodRiskSnapshot.issued_at == issued)
                            .order_by(FloodRiskSnapshot.horizon_h))) if issued else []
    return {"area": AreaOut.model_validate(a), "source": a.source.name, "issued_at": issued,
            "risk": [{"horizon_h": s.horizon_h, "risk_level": s.risk_level, "score": s.score,
                      "flood_probability": s.flood_probability, "rainfall_mm": s.rainfall_mm,
                      "water_level_ratio": s.water_level_ratio, "camera_flood_ratio": s.camera_flood_ratio,
                      "explanation": explanation_for(s.explanation, user), "is_simulated": s.is_simulated}
                     for s in snaps]}


@router.get("/traffic-cameras")
def traffic_cameras(db: DB):
    rows = db.execute(select(Camera.id, Camera.name, Camera.longitude, Camera.latitude).where(
        Camera.code.like(traffic_camera_service.CODE_PREFIX + "%"), Camera.status == "ACTIVE",
        Camera.deleted_at.is_(None))).all()
    return {"type": "FeatureCollection", "features": [_pt(r[2], r[3], {"id": r[0], "name": r[1]}) for r in rows],
            "attribution": "Camera: Cổng thông tin giao thông TP.HCM"}


@router.post("/import")
async def import_boundaries(user: Admin, request: Request, db: DB, file: UploadFile = File(...),
                            level: str = Query("WARD", pattern="^(DISTRICT|WARD)$"),
                            name_field: str = "name", code_field: str = "code",
                            source_name: str = Query("Ranh giới do quản trị viên nhập", max_length=200)):
    content = await file.read(30 * 1024 * 1024 + 1)
    if len(content) > 30 * 1024 * 1024:
        raise AppError(413, "TOO_LARGE", "GeoJSON tối đa 30 MB")
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise AppError(422, "INVALID_GEOJSON", "Tệp không phải GeoJSON hợp lệ") from e
    code = "GIS-" + hashlib.sha1(source_name.encode()).hexdigest()[:12]
    src = db.scalar(select(DataSource).where(DataSource.code == code))
    if not src:
        src = DataSource(code=code, name=source_name, kind="OPEN_DATA", is_simulated=False)
        db.add(src)
        db.flush()
    n = import_geojson(db, data, src, level, name_field, code_field)
    audit(db, user, "GIS_IMPORT", "administrative_area", "", {"inserted": n, "level": level}, request)
    db.commit()
    return {"inserted": n}
