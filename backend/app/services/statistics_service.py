"""Thống kê tính ở backend (SQL aggregate). Cùng các hàm truy vấn được dùng cho API và xuất Excel."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, and_, case, func, literal_column, or_, select

from app.core.database import utcnow
from app.models import (
    AdministrativeArea,
    Alert,
    AlertHistory,
    Camera,
    CameraDetection,
    FloodRiskSnapshot,
    Forecast,
    HistoricalFloodEvent,
    ModelVersion,
    MonitoringStation,
    RainfallObservation,
    WaterLevelObservation,
)
from app.services import simulation_overlay
from app.services.station_service import connection_status

VN = timedelta(hours=7)


@dataclass
class Filters:
    date_from: datetime  # UTC naive
    date_to: datetime  # UTC naive, loại trừ
    area_id: int | None = None
    station_id: int | None = None
    risk_level: str | None = None
    data_type: str | None = None  # SIMULATED / REAL / None=tất cả

    def as_dict(self) -> dict:
        return {k: (v.isoformat() + "Z" if isinstance(v, datetime) else v) for k, v in vars(self).items()}


def _sim(col, f: Filters):
    if f.data_type == "SIMULATED":
        return col.is_(True)
    if f.data_type == "REAL":
        return col.is_(False)
    return True


def _obs_stmt(model, value_col, f: Filters) -> Select:
    stmt = (select(model.observed_at, MonitoringStation.code, MonitoringStation.name, AdministrativeArea.name,
                   value_col, model.quality_flag, model.is_simulated)
            .join(MonitoringStation, MonitoringStation.id == model.station_id)
            .outerjoin(AdministrativeArea, AdministrativeArea.id == MonitoringStation.area_id)
            .where(model.observed_at >= f.date_from, model.observed_at < f.date_to, _sim(model.is_simulated, f)))
    if f.station_id:
        stmt = stmt.where(model.station_id == f.station_id)
    if f.area_id:
        stmt = stmt.where(MonitoringStation.area_id == f.area_id)
    return stmt


def rainfall_rows(db, f, limit=None):
    stmt = _obs_stmt(RainfallObservation, RainfallObservation.rainfall_mm, f).order_by(
        RainfallObservation.observed_at, MonitoringStation.code)
    return db.execute(stmt.limit(limit) if limit else stmt).all()


def water_rows(db, f, limit=None):
    stmt = _obs_stmt(WaterLevelObservation, WaterLevelObservation.water_level_cm, f).order_by(
        WaterLevelObservation.observed_at, MonitoringStation.code)
    return db.execute(stmt.limit(limit) if limit else stmt).all()


def obs_page(db, f, kind: str, page: int, size: int):
    model, col = ((RainfallObservation, RainfallObservation.rainfall_mm) if kind == "rainfall"
                  else (WaterLevelObservation, WaterLevelObservation.water_level_cm))
    stmt = _obs_stmt(model, col, f)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(model.observed_at.desc(), MonitoringStation.code)
                      .offset((page - 1) * size).limit(size)).all()
    return rows, total


def _bucket(col, group: str):
    # gom nhóm theo giờ Việt Nam
    local = col + literal_column("interval '7 hours'")
    fmt = {"hour": 'YYYY-MM-DD HH24":00"', "day": "YYYY-MM-DD", "month": "YYYY-MM", "year": "YYYY"}[group]
    # định dạng là literal (không bind) để GROUP BY khớp biểu thức SELECT
    return func.to_char(local, literal_column(f"'{fmt}'"))



def obs_series(db, f: Filters, kind: str, group: str = "day") -> list[dict]:
    model, col = ((RainfallObservation, RainfallObservation.rainfall_mm) if kind == "rainfall"
                  else (WaterLevelObservation, WaterLevelObservation.water_level_cm))
    b = _bucket(model.observed_at, group).label("bucket")
    agg = [func.sum(col), func.avg(col), func.max(col), func.count(col)]
    stmt = (select(b, *agg).join(MonitoringStation, MonitoringStation.id == model.station_id)
            .where(model.observed_at >= f.date_from, model.observed_at < f.date_to, model.quality_flag == "VALID",
                   _sim(model.is_simulated, f)).group_by(b).order_by(b))
    if f.station_id:
        stmt = stmt.where(model.station_id == f.station_id)
    if f.area_id:
        stmt = stmt.where(MonitoringStation.area_id == f.area_id)
    return [{"bucket": r[0], "sum": _r(r[1]), "avg": _r(r[2]), "max": _r(r[3]), "count": r[4]}
            for r in db.execute(stmt)]


def by_station(db, f: Filters, kind: str) -> list[dict]:
    model, col = ((RainfallObservation, RainfallObservation.rainfall_mm) if kind == "rainfall"
                  else (WaterLevelObservation, WaterLevelObservation.water_level_cm))
    stmt = (select(MonitoringStation.id, MonitoringStation.code, MonitoringStation.name, func.sum(col),
                   func.avg(col), func.max(col), func.count(col))
            .join(model, model.station_id == MonitoringStation.id)
            .where(model.observed_at >= f.date_from, model.observed_at < f.date_to, model.quality_flag == "VALID",
                   _sim(model.is_simulated, f)).group_by(MonitoringStation.id).order_by(MonitoringStation.code))
    if f.station_id:
        stmt = stmt.where(MonitoringStation.id == f.station_id)
    if f.area_id:
        stmt = stmt.where(MonitoringStation.area_id == f.area_id)
    return [{"station_id": r[0], "code": r[1], "name": r[2], "sum": _r(r[3]), "avg": _r(r[4]), "max": _r(r[5]),
             "count": r[6]} for r in db.execute(stmt)]


def _r(v, n=2):
    return None if v is None else round(float(v), n)


def alert_stmt(f: Filters) -> Select:
    stmt = select(Alert).where(Alert.triggered_at >= f.date_from, Alert.triggered_at < f.date_to,
                               _sim(Alert.is_simulated, f))
    if f.area_id:
        stmt = stmt.where(Alert.area_id == f.area_id)
    if f.risk_level:
        stmt = stmt.where(Alert.risk_level == f.risk_level)
    return stmt


def alert_stats(db, f: Filters, group: str = "day") -> dict:
    base = alert_stmt(f).subquery()
    b = _bucket(base.c.triggered_at, group).label("b")
    by_time = [{"bucket": r[0], "LOW": r[1], "MEDIUM": r[2], "HIGH": r[3], "total": r[4]} for r in db.execute(
        select(b, *[func.sum(case((base.c.risk_level == lv, 1), else_=0)) for lv in ("LOW", "MEDIUM", "HIGH")],
               func.count()).group_by(b).order_by(b))]
    by_area = [{"area": r[0], "count": r[1]} for r in db.execute(
        select(AdministrativeArea.name, func.count()).join(base, base.c.area_id == AdministrativeArea.id)
        .group_by(AdministrativeArea.name).order_by(func.count().desc()))]
    by_level = dict(db.execute(select(base.c.risk_level, func.count()).group_by(base.c.risk_level)).all())
    by_status = dict(db.execute(select(base.c.status, func.count()).group_by(base.c.status)).all())
    verified = dict(db.execute(select(base.c.verified_outcome, func.count()).group_by(base.c.verified_outcome)).all())
    def mins(end):
        return func.avg(func.extract("epoch", end - base.c.triggered_at) / 60)

    ack = db.execute(select(mins(base.c.acknowledged_at), mins(base.c.resolved_at))).one()
    conf, fa = verified.get("CONFIRMED", 0), verified.get("FALSE_ALARM", 0)
    return {
        "total": sum(by_level.values()), "by_time": by_time, "by_area": by_area, "by_level": by_level,
        "by_status": by_status, "verification": verified,
        "precision_verified": round(conf / (conf + fa), 4) if conf + fa else None,
        "avg_minutes_to_ack": _r(ack[0], 1), "avg_minutes_to_resolve": _r(ack[1], 1),
    }



def risk_trend(db, f: Filters, group: str = "day") -> list[dict]:
    b = _bucket(FloodRiskSnapshot.issued_at, group).label("b")
    stmt = (select(b, *[func.sum(case((FloodRiskSnapshot.risk_level == lv, 1), else_=0))
                        for lv in ("LOW", "MEDIUM", "HIGH", "INSUFFICIENT_DATA")], func.avg(FloodRiskSnapshot.score))
            .join(AdministrativeArea, AdministrativeArea.id == FloodRiskSnapshot.area_id)
            .where(FloodRiskSnapshot.issued_at >= f.date_from, FloodRiskSnapshot.issued_at < f.date_to,
                   FloodRiskSnapshot.horizon_h == 0, AdministrativeArea.level == "DISTRICT").group_by(b).order_by(b))
    if f.area_id:
        stmt = stmt.where(FloodRiskSnapshot.area_id == f.area_id)
    return [{"bucket": r[0], "LOW": r[1], "MEDIUM": r[2], "HIGH": r[3], "INSUFFICIENT_DATA": r[4],
             "avg_score": _r(r[5], 3)} for r in db.execute(stmt)]


def latest_risk_counts(db, sim: dict | None = None) -> dict:
    """Số quận theo mức rủi ro hiện tại; sim (simulation_overlay.affected) nâng mức các quận bị mô phỏng."""
    issued = db.scalar(select(func.max(FloodRiskSnapshot.issued_at)))
    if not issued:
        return {}
    rows = db.execute(select(FloodRiskSnapshot.area_id, FloodRiskSnapshot.risk_level).join(
        AdministrativeArea, AdministrativeArea.id == FloodRiskSnapshot.area_id).where(
        FloodRiskSnapshot.issued_at == issued, FloodRiskSnapshot.horizon_h == 0,
        AdministrativeArea.level == "DISTRICT"))
    out: dict = {}
    for aid, lv in rows:
        lv = simulation_overlay.overlay_risk({"risk_level": lv}, (sim or {}).get(aid))["risk_level"]
        out[lv] = out.get(lv, 0) + 1
    return out


def with_simulation_overview(db, o: dict, sim: dict) -> dict:
    """Tổng quan có tính vùng ngập mô phỏng đang bật (chỉ cán bộ)."""
    if not sim:
        return {**o, "simulation": None}
    risk = latest_risk_counts(db, sim)
    n_alerts = sum(1 for a in sim.values() if a["level"] == "DISTRICT")
    return {**o, "areas_low": risk.get("LOW", 0), "areas_medium": risk.get("MEDIUM", 0),
            "areas_high": risk.get("HIGH", 0), "alerts_active": o["alerts_active"] + n_alerts,
            "simulation": {"districts": n_alerts, "wards": sum(1 for a in sim.values() if a["level"] == "WARD")}}


def with_simulation_alerts(s: dict, sims: list[dict]) -> dict:
    """Thống kê cảnh báo cộng cảnh báo mô phỏng (theo mức, khu vực, trạng thái NEW); by_time giữ nguyên dữ liệu thật."""
    if not sims:
        return {**s, "simulated": 0}
    by_level, by_status = dict(s["by_level"]), dict(s["by_status"])
    by_area = {r["area"]: r["count"] for r in s["by_area"]}
    for v in sims:
        by_level[v["risk_level"]] = by_level.get(v["risk_level"], 0) + 1
        by_status["NEW"] = by_status.get("NEW", 0) + 1
        by_area[v["area"].name] = by_area.get(v["area"].name, 0) + 1
    return {**s, "total": s["total"] + len(sims), "by_level": by_level, "by_status": by_status,
            "by_area": [{"area": k, "count": c} for k, c in sorted(by_area.items(), key=lambda x: -x[1])],
            "simulated": len(sims)}


def forecast_rows(db, f: Filters, limit=None):
    stmt = (select(Forecast.issued_at, Forecast.target_time, Forecast.horizon_h, MonitoringStation.code,
                   MonitoringStation.name, Forecast.rainfall_mm, Forecast.water_level_cm, Forecast.flood_probability,
                   Forecast.data_quality, Forecast.is_cold_start, Forecast.is_simulated, ModelVersion.name,
                   ModelVersion.version)
            .join(MonitoringStation, MonitoringStation.id == Forecast.station_id)
            .outerjoin(ModelVersion, ModelVersion.id == Forecast.model_version_id)
            .where(Forecast.issued_at >= f.date_from, Forecast.issued_at < f.date_to, _sim(Forecast.is_simulated, f))
            .order_by(Forecast.issued_at, MonitoringStation.code, Forecast.horizon_h))
    if f.station_id:
        stmt = stmt.where(Forecast.station_id == f.station_id)
    if f.area_id:
        stmt = stmt.where(Forecast.area_id == f.area_id)
    return db.execute(stmt.limit(limit) if limit else stmt).all()


def forecast_skill(db, f: Filters) -> list[dict]:
    """Đối chiếu dự báo mưa với quan trắc thực tế tại target_time (MAE/RMSE theo horizon)."""
    stmt = (select(Forecast.horizon_h, func.avg(func.abs(Forecast.rainfall_mm - RainfallObservation.rainfall_mm)),
                   func.sqrt(func.avg(func.pow(Forecast.rainfall_mm - RainfallObservation.rainfall_mm, 2))),
                   func.count())
            .join(RainfallObservation, and_(RainfallObservation.station_id == Forecast.station_id,
                                            RainfallObservation.observed_at == Forecast.target_time,
                                            RainfallObservation.quality_flag == "VALID"))
            .where(Forecast.issued_at >= f.date_from, Forecast.issued_at < f.date_to)
            .group_by(Forecast.horizon_h).order_by(Forecast.horizon_h))
    if f.station_id:
        stmt = stmt.where(Forecast.station_id == f.station_id)
    return [{"horizon_h": r[0], "mae": _r(r[1], 3), "rmse": _r(r[2], 3), "n": r[3]} for r in db.execute(stmt)]


def model_performance(db, f: Filters) -> dict:
    models = list(db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc())))
    return {
        "models": [{"id": m.id, "name": m.name, "type": m.model_type, "version": m.version, "active": m.is_active,
                    "trained_on_simulated": m.trained_on_simulated, "metrics": m.metrics} for m in models],
        "online_rainfall_skill": forecast_skill(db, f),
        "alert_verification": alert_stats(db, f)["verification"],
    }


def flood_event_stmt(f: Filters) -> Select:
    stmt = select(HistoricalFloodEvent).where(HistoricalFloodEvent.started_at >= f.date_from,
                                              HistoricalFloodEvent.started_at < f.date_to,
                                              _sim(HistoricalFloodEvent.is_simulated, f))
    if f.area_id:
        stmt = stmt.where(HistoricalFloodEvent.area_id == f.area_id)
    return stmt


def flood_event_stats(db, f: Filters, group="month") -> dict:
    sub = flood_event_stmt(f).subquery()
    b = _bucket(sub.c.started_at, group).label("b")
    return {
        "by_time": [{"bucket": r[0], "count": r[1], "max_depth_cm": _r(r[2])} for r in db.execute(
            select(b, func.count(), func.max(sub.c.max_depth_cm)).group_by(b).order_by(b))],
        "by_area": [{"area": r[0], "count": r[1]} for r in db.execute(
            select(AdministrativeArea.name, func.count()).join(sub, sub.c.area_id == AdministrativeArea.id)
            .group_by(AdministrativeArea.name).order_by(func.count().desc()))],
        "total": db.scalar(select(func.count()).select_from(sub)),
    }


def data_quality(db, f: Filters) -> list[dict]:
    out = []
    for name, model in (("Lượng mưa", RainfallObservation), ("Mực nước", WaterLevelObservation)):
        stmt = (select(MonitoringStation.code, MonitoringStation.name, model.quality_flag, func.count())
                .join(MonitoringStation, MonitoringStation.id == model.station_id)
                .where(model.observed_at >= f.date_from, model.observed_at < f.date_to)
                .group_by(MonitoringStation.code, MonitoringStation.name, model.quality_flag))
        if f.station_id:
            stmt = stmt.where(model.station_id == f.station_id)
        if f.area_id:
            stmt = stmt.where(MonitoringStation.area_id == f.area_id)
        agg: dict = {}
        for code, sname, flag, c in db.execute(stmt):
            agg.setdefault((code, sname), {})[flag] = c
        for (code, sname), flags in sorted(agg.items()):
            total = sum(flags.values())
            out.append({"kind": name, "code": code, "name": sname, "total": total, **flags,
                        "valid_ratio": round(flags.get("VALID", 0) / total, 4) if total else None})
    return out


def station_status(db) -> list[dict]:
    rows = []
    for s in db.scalars(select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None))
                        .order_by(MonitoringStation.code)):
        rows.append({"id": s.id, "code": s.code, "name": s.name, "type": s.station_type, "status": s.status,
                     "connection": connection_status(s), "area": s.area.name if s.area else None,
                     "area_id": s.area_id, "last_observation_at": s.last_observation_at, "source": s.source.name,
                     "is_simulated": s.source.is_simulated, "latitude": s.latitude, "longitude": s.longitude,
                     "managing_unit": s.managing_unit, "interval_minutes": s.interval_minutes,
                     "flood_threshold_cm": s.flood_threshold_cm})
    return rows


def camera_status(db, f: Filters) -> list[dict]:
    rows = []
    # camera giao thông không qua phân tích ảnh nên không thuộc thống kê này
    for c in db.scalars(select(Camera).where(Camera.deleted_at.is_(None), Camera.code.not_like("TT-%")).order_by(Camera.code)):
        q = db.execute(select(func.count(), func.max(CameraDetection.flood_ratio), func.avg(CameraDetection.flood_ratio),
                              func.max(CameraDetection.detected_at))
                       .where(CameraDetection.camera_id == c.id, CameraDetection.detected_at >= f.date_from,
                              CameraDetection.detected_at < f.date_to)).one()
        rows.append({"id": c.id, "code": c.code, "name": c.name, "status": c.status,
                     "area": c.area.name if c.area else None, "is_public": c.is_public,
                     "is_simulated": c.source.is_simulated, "detections": q[0], "max_flood_ratio": _r(q[1], 4),
                     "avg_flood_ratio": _r(q[2], 4), "last_detection_at": q[3]})
    return rows


def alert_handling(db, f: Filters) -> list[dict]:
    stmt = (select(AlertHistory.action, AlertHistory.to_status, func.count())
            .join(Alert, Alert.id == AlertHistory.alert_id)
            .where(AlertHistory.changed_at >= f.date_from, AlertHistory.changed_at < f.date_to)
            .group_by(AlertHistory.action, AlertHistory.to_status))
    return [{"action": r[0], "to_status": r[1], "count": r[2]} for r in db.execute(stmt)]


def overview(db, f: Filters) -> dict:
    stations = station_status(db)
    rain_avg = db.scalar(select(func.avg(RainfallObservation.rainfall_mm)).where(
        RainfallObservation.observed_at >= f.date_from, RainfallObservation.observed_at < f.date_to,
        RainfallObservation.quality_flag == "VALID", _sim(RainfallObservation.is_simulated, f)))
    wl_max = db.scalar(select(func.max(WaterLevelObservation.water_level_cm)).where(
        WaterLevelObservation.observed_at >= f.date_from, WaterLevelObservation.observed_at < f.date_to,
        WaterLevelObservation.quality_flag == "VALID", _sim(WaterLevelObservation.is_simulated, f)))
    q_total = q_valid = 0
    for model in (RainfallObservation, WaterLevelObservation):
        t, v = db.execute(select(func.count(), func.sum(case((model.quality_flag == "VALID", 1), else_=0)))
                          .where(model.observed_at >= f.date_from, model.observed_at < f.date_to)).one()
        q_total += t or 0
        q_valid += int(v or 0)
    risk = latest_risk_counts(db)
    a = alert_stats(db, f)
    open_alerts = db.scalar(select(func.count()).select_from(Alert).where(
        Alert.status.in_(["NEW", "ACKNOWLEDGED", "IN_PROGRESS"])))
    return {
        "stations_total": len(stations),
        "stations_online": sum(s["connection"] == "ONLINE" for s in stations),
        "stations_offline": sum(s["connection"] != "ONLINE" for s in stations),
        "cameras_total": db.scalar(select(func.count()).select_from(Camera).where(
            Camera.deleted_at.is_(None), Camera.code.not_like("TT-%"))),
        "areas_total": db.scalar(select(func.count()).select_from(AdministrativeArea).where(
            AdministrativeArea.level == "DISTRICT")),
        "areas_low": risk.get("LOW", 0), "areas_medium": risk.get("MEDIUM", 0), "areas_high": risk.get("HIGH", 0),
        "areas_insufficient": risk.get("INSUFFICIENT_DATA", 0),
        "alerts_active": open_alerts,
        "alerts_in_range": a["total"],
        "alerts_handled": a["by_status"].get("RESOLVED", 0) + a["by_status"].get("CLOSED", 0),
        "rainfall_avg_mm": _r(rain_avg, 3), "water_level_max_cm": _r(wl_max, 1),
        "latest_forecast_at": db.scalar(select(func.max(Forecast.issued_at))),
        "valid_data_ratio": round(q_valid / q_total, 4) if q_total else None,
        "generated_at": utcnow(),
    }


def satellite_vs_model(db, f: Filters) -> list[dict]:
    """Mưa trung bình mỗi quận theo ngày UTC: vệ tinh GPM IMERG (đo) và Open-Meteo (mô hình, tổng giờ trong ngày)."""
    from app.models import SatelliteRainfallDaily as S

    d0, d1 = f.date_from.date(), f.date_to.date()
    q = select(S.day, func.avg(S.rain_mm)).where(S.day >= d0, S.day <= d1)
    if f.area_id:
        q = q.where(S.area_id == f.area_id)
    sat = dict(db.execute(q.group_by(S.day)).all())
    if not sat:
        return []
    day = func.date(RainfallObservation.observed_at)
    om = select(day.label("d"), MonitoringStation.id, func.sum(RainfallObservation.rainfall_mm).label("mm")).join(
        MonitoringStation, MonitoringStation.id == RainfallObservation.station_id).where(
        MonitoringStation.code.like("OM-%"), MonitoringStation.code != "OM-TIDE-VT",
        RainfallObservation.observed_at >= f.date_from, RainfallObservation.observed_at < f.date_to,
        RainfallObservation.quality_flag != "SUSPECT")
    if f.area_id:
        om = om.join(AdministrativeArea, AdministrativeArea.id == MonitoringStation.area_id).where(
            or_(AdministrativeArea.id == f.area_id, AdministrativeArea.parent_id == f.area_id))
    om = om.group_by(day, MonitoringStation.id).subquery()
    model = dict(db.execute(select(om.c.d, func.avg(om.c.mm)).group_by(om.c.d)).all())
    return [{"day": d.isoformat(), "imerg_mm": _r(sat[d], 2), "model_mm": _r(model.get(d), 2)} for d in sorted(sat)]
