from collections import defaultdict

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import DB, OptionalUser, explanation_for, is_staff
from app.core.errors import NotFound
from app.jobs import pipeline
from app.models import AdministrativeArea, FloodRiskSnapshot, Forecast, ModelVersion, MonitoringStation
from app.schemas.views import ModelVersionOut, RiskOut, StationForecast
from app.services import forecast_service, gis_service, simulation_overlay

router = APIRouter(prefix="/forecasts", tags=["Forecasts"])


def _group(db, rows) -> list[StationForecast]:
    by_st = defaultdict(list)
    for f in rows:
        by_st[f.station_id].append(f)
    stations = {s.id: s for s in db.scalars(select(MonitoringStation).where(MonitoringStation.id.in_(list(by_st))))}
    models = {m.id: m for m in db.scalars(select(ModelVersion))}
    out = []
    for sid, fs in by_st.items():
        s, f0 = stations[sid], fs[0]
        mv = models.get(f0.model_version_id)
        out.append(StationForecast(
            station_id=sid, station_code=s.code, station_name=s.name, area_id=s.area_id, issued_at=f0.issued_at,
            model_version=f"{mv.name}:{mv.version}" if mv else None, data_quality=f0.data_quality,
            is_cold_start=f0.is_cold_start, is_simulated=f0.is_simulated,
            points=[{"horizon_h": f.horizon_h, "target_time": f.target_time, "rainfall_mm": f.rainfall_mm,
                     "water_level_cm": f.water_level_cm, "flood_probability": f.flood_probability}
                    for f in sorted(fs, key=lambda x: x.horizon_h)]))
    return sorted(out, key=lambda x: x.station_code)


@router.get("/latest", response_model=list[StationForecast])
def latest(db: DB, area_id: int | None = None):
    issued = db.scalar(select(func.max(Forecast.issued_at)))
    if not issued:
        return []
    stmt = select(Forecast).where(Forecast.issued_at == issued)
    if area_id:
        stmt = stmt.where(Forecast.area_id == area_id)
    return _group(db, db.scalars(stmt))


@router.get("", response_model=list[StationForecast])
def history(db: DB, station_id: int, limit: int = Query(24, ge=1, le=168)):
    """Các lần phát hành gần nhất của một trạm."""
    issues = list(db.scalars(select(Forecast.issued_at).where(Forecast.station_id == station_id).distinct()
                             .order_by(Forecast.issued_at.desc()).limit(limit)))
    rows = db.scalars(select(Forecast).where(Forecast.station_id == station_id, Forecast.issued_at.in_(issues)))
    groups = defaultdict(list)
    for f in rows:
        groups[f.issued_at].append(f)
    return [g for k in sorted(groups, reverse=True) for g in _group(db, groups[k])]


@router.get("/risk", response_model=list[RiskOut])
def risk(db: DB, user: OptionalUser, horizon: int = Query(0, ge=0, le=6),
         level: str = Query("DISTRICT", pattern="^(DISTRICT|WARD)$")):
    issued = gis_service.latest_issue_time(db)
    if not issued:
        return []
    names = {a.id: a.name for a in db.scalars(select(AdministrativeArea).where(AdministrativeArea.level == level))}
    aff = simulation_overlay.affected(db) if is_staff(user) else {}
    rows = [RiskOut(**simulation_overlay.overlay_risk(dict(
        area_id=s.area_id, area_name=names[s.area_id], horizon_h=s.horizon_h, issued_at=s.issued_at,
        risk_level=s.risk_level, score=s.score, flood_probability=s.flood_probability, rainfall_mm=s.rainfall_mm,
        water_level_ratio=s.water_level_ratio, camera_flood_ratio=s.camera_flood_ratio,
        explanation=explanation_for(s.explanation, user), is_simulated=s.is_simulated), aff.get(s.area_id)))
        for s in db.scalars(select(FloodRiskSnapshot).where(FloodRiskSnapshot.issued_at == issued,
                                                            FloodRiskSnapshot.horizon_h == horizon,
                                                            FloodRiskSnapshot.area_id.in_(list(names)))
                            .order_by(FloodRiskSnapshot.score.desc()))]
    rank = simulation_overlay.RANK
    return sorted(rows, key=lambda r: -rank.get(r.risk_level, 0)) if aff else rows


@router.get("/area/{aid}")
def area_forecast(aid: int, db: DB, user: OptionalUser):
    if not db.get(AdministrativeArea, aid):
        raise NotFound("Khu vực")
    issued = gis_service.latest_issue_time(db)
    snaps = list(db.scalars(select(FloodRiskSnapshot).where(FloodRiskSnapshot.area_id == aid,
                                                            FloodRiskSnapshot.issued_at == issued)
                            .order_by(FloodRiskSnapshot.horizon_h))) if issued else []
    sim = simulation_overlay.affected(db).get(aid) if is_staff(user) else None
    return {"area_id": aid, "issued_at": issued, "risk": [simulation_overlay.overlay_risk(
        {"horizon_h": s.horizon_h, "risk_level": s.risk_level, "score": s.score,
         "flood_probability": s.flood_probability, "rainfall_mm": s.rainfall_mm}, sim) for s in snaps],
        "stations": latest(db, aid)}


@router.get("/model-status")
def model_status(db: DB):
    mv = forecast_service.active_model(db)
    vis = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True),
                                               ModelVersion.model_type == "YOLOV8_SEG"))
    return {
        "forecast_model": ModelVersionOut.model_validate(mv) if mv else None,
        "vision_model": ModelVersionOut.model_validate(vis) if vis else None,
        "latest_issued_at": db.scalar(select(func.max(Forecast.issued_at))),
        "last_cycle": {k: v for k, v in pipeline.last_run.items() if k in ("seconds", "issued_at", "alerts")},
        "warning": "Mô hình được huấn luyện/đánh giá trên dữ liệu MÔ PHỎNG; chưa kiểm chứng với dữ liệu quan trắc thực."
        if mv and mv.trained_on_simulated else None,
    }
