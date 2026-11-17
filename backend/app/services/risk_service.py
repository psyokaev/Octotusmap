"""Tổng hợp dữ liệu theo khu vực, áp dụng rule engine, lưu flood_risk_snapshots."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, aliased

from app.models import (
    AdministrativeArea,
    AlertRule,
    Camera,
    CameraDetection,
    FloodHotspot,
    FloodReport,
    FloodRiskSnapshot,
    Forecast,
    HistoricalFloodEvent,
    MonitoringStation,
)
from app.repositories import observations as obs_repo
from app.repositories.base import contains
from app.services import flood_index, gis_service
from app.services.rule_engine import DEFAULT_RULE_CONFIG, RiskInputs, evaluate

NEIGHBOR_MAX_M = 6000
CAMERA_MAX_AGE = timedelta(minutes=90)
TIDAL_DISTRICTS = ("Quận 7", "Huyện Nhà Bè", "Huyện Cần Giờ", "Quận 8", "Quận 4", "Quận 2", "Quận Bình Thạnh",
                   "Quận Thủ Đức")
SEVERE_EVENT_CM, SEVERE_RADIUS_M, MAX_WARD_NAMES = 30, 500, 8


def tide_exposed_wards(db: Session) -> set[int]:
    """Phường thấp (< LOW_ELEVATION_M) thuộc quận ven sông/triều, cộng phường có điểm ngập do triều cường."""
    d = aliased(AdministrativeArea)
    ids = set(db.scalars(select(AdministrativeArea.id).join(d, d.id == AdministrativeArea.parent_id).where(
        AdministrativeArea.level == "WARD", AdministrativeArea.elevation_m < flood_index.LOW_ELEVATION_M,
        d.name.in_(TIDAL_DISTRICTS))))
    # shortcut: hotspot chưa có cột cause nên lọc theo note, đổi khi thêm cột
    return ids | set(db.scalars(select(FloodHotspot.area_id).join(
        AdministrativeArea, AdministrativeArea.id == FloodHotspot.area_id).where(
        AdministrativeArea.level == "WARD", contains(FloodHotspot.note, "triều cường"))))


def severe_hotspot_wards(db: Session, issued_at: datetime) -> set[int]:
    """Phường có điểm ngập nằm trong 500 m của một trận ngập lịch sử sâu >= 30 cm."""
    from app.services.routing_service import dist_m  # import trong hàm để tránh vòng với routing_service

    ev = [(e.longitude, e.latitude) for e in db.scalars(select(HistoricalFloodEvent).where(
        HistoricalFloodEvent.max_depth_cm >= SEVERE_EVENT_CM, HistoricalFloodEvent.started_at <= issued_at))]
    return {h.area_id for h in db.scalars(select(FloodHotspot).where(FloodHotspot.area_id.is_not(None)))
            if any(dist_m((h.longitude, h.latitude), e) <= SEVERE_RADIUS_M for e in ev)}


def active_rule(db: Session) -> AlertRule | None:
    return db.scalar(select(AlertRule).where(AlertRule.is_active.is_(True)).order_by(AlertRule.version.desc()))


def _area_station_map(db: Session, stations, areas) -> dict[int, tuple[list[int], bool]]:
    """{area_id: ([station_ids], dùng_trạm_lân_cận)}."""
    by_area = defaultdict(list)
    for s in stations:
        if s.area_id:
            by_area[s.area_id].append(s.id)
    out = {}
    for a in areas:
        if by_area.get(a.id):
            out[a.id] = (by_area[a.id], False)
        elif a.level == "WARD" and by_area.get(a.parent_id):  # phường dùng điểm mưa của quận cha
            out[a.id] = (by_area[a.parent_id], False)
        else:
            near = gis_service.nearest_stations(db, a.centroid_lon, a.centroid_lat, 2, NEIGHBOR_MAX_M)
            out[a.id] = ([sid for sid, _ in near], True)
    return out


def camera_ratios(code: str, ratios_newest_first: list[float], threshold: float) -> list[float]:
    """Camera giao thông tự quét: chỉ tính khi 2 phát hiện gần nhất đều >= ngưỡng (chống báo động giả), lấy giá trị thấp.
    Camera nhập tay giữ nguyên."""
    if not code.startswith("TT-"):
        return ratios_newest_first
    two = ratios_newest_first[:2]
    return [min(two)] if len(two) == 2 and min(two) >= threshold else []


def storm_counts(stations: dict, issued_at: datetime) -> dict[int, int]:
    """Trạm Open-Meteo -> số mô hình báo mưa dông. Rỗng khi DEMO, khi tính lại quá khứ hoặc khi API lỗi."""
    from app.core.config import get_settings
    from app.core.database import utcnow
    from app.services import openmeteo_service as om

    if get_settings().demo_mode or abs(utcnow() - issued_at) > timedelta(hours=3):
        return {}  # Open-Meteo không lưu dự báo đa mô hình đã phát trong quá khứ
    pts = [s for s in stations.values() if s.source.code == om.SOURCE_CODE and s.code != om.TIDE_CODE]
    try:
        counts = om.storm_model_counts([(s.latitude, s.longitude) for s in pts], issued_at) if pts else []
    except Exception:  # thiếu tín hiệu phụ không được làm hỏng cả chu kỳ đánh giá
        logging.getLogger(__name__).warning("không lấy được dự báo đa mô hình", exc_info=True)
        return {}
    return {s.id: n for s, n in zip(pts, counts, strict=True)}


def evaluate_all(db: Session, issued_at: datetime) -> dict:
    rule = active_rule(db)
    cfg = rule.config if rule else DEFAULT_RULE_CONFIG
    areas = sorted(db.scalars(select(AdministrativeArea)), key=lambda a: a.level != "WARD")  # phường trước quận
    stations = {s.id: s for s in db.scalars(select(MonitoringStation).where(
        MonitoringStation.deleted_at.is_(None), MonitoringStation.status == "ACTIVE"))}
    mapping = _area_station_map(db, stations.values(), areas)
    latest = obs_repo.latest_values(db, list(stations), issued_at)
    fc = defaultdict(dict)  # station -> horizon -> Forecast
    for f in db.scalars(select(Forecast).where(Forecast.issued_at == issued_at)):
        fc[f.station_id][f.horizon_h] = f
    cams = defaultdict(list)
    det_rows = db.execute(
        select(Camera.area_id, Camera.longitude, Camera.latitude, CameraDetection.flood_ratio, Camera.code,
               CameraDetection.detected_at)
        .join(Camera, Camera.id == CameraDetection.camera_id)
        .where(CameraDetection.detected_at >= issued_at - CAMERA_MAX_AGE,
                CameraDetection.detected_at <= issued_at + timedelta(hours=1),  # live: issued_at chậm hơn thực tế
                CameraDetection.method == "YOLOV8_SEG",  # heuristic HSV không được dựng cảnh báo
                Camera.deleted_at.is_(None))).all()
    from app.core.config import get_settings

    wards_of: dict = {}  # (lon, lat) -> id phường chứa camera; chỉ camera có phát hiện gần đây nên ít lần truy vấn
    thr = cfg["overrides"]["camera_ratio_high"]
    by_cam = defaultdict(list)
    for r in (det_rows if get_settings().camera_enabled else ()):
        by_cam[(r[0], r[1], r[2], r[4])].append((r[5], r[3]))
    for (aid, lon, lat, code), dets in by_cam.items():
        ratios = [x for _, x in sorted(dets, reverse=True)]  # mới nhất trước
        for ratio in camera_ratios(code, ratios, thr):
            if (lon, lat) not in wards_of:
                w = gis_service.area_at(db, lon, lat, "WARD")
                wards_of[(lon, lat)] = w.id if w else aid
            cams[wards_of[(lon, lat)]].append(ratio)
    prev = {(s.area_id, s.horizon_h): s.risk_level for s in db.scalars(
        select(FloodRiskSnapshot).where(FloodRiskSnapshot.issued_at == select(func.max(FloodRiskSnapshot.issued_at))
                                        .where(FloodRiskSnapshot.issued_at < issued_at).scalar_subquery()))}

    from app.services import openmeteo_service as om

    tstats = om.tide_stats(db)
    hot_wards = set(db.scalars(select(FloodHotspot.area_id).distinct()))
    exposed, severe = tide_exposed_wards(db), severe_hotspot_wards(db, issued_at)
    reports = defaultdict(list)  # không dùng report_service.active (utcnow) vì backfill đánh giá quá khứ
    for rp in db.scalars(select(FloodReport).where(
            FloodReport.expires_at > issued_at, FloodReport.status != "REJECTED",
            FloodReport.reported_at <= issued_at + timedelta(hours=1), FloodReport.area_id.is_not(None))):
        reports[rp.area_id].append(rp)
    kids = defaultdict(list)  # (quận, mốc) -> kết quả các phường con
    storm = storm_counts(stations, issued_at)
    tide = {h: om.tide_ratio(om.tide_at(db, issued_at + timedelta(hours=h)), tstats) for h in range(0, 7)}
    # hai lượt đánh giá cùng issued_at (pipeline + kích hoạt tay) phải tuần tự, nếu không xoá/chèn chéo nhau -> trùng dòng
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int(issued_at.timestamp())})
    db.execute(delete(FloodRiskSnapshot).where(FloodRiskSnapshot.issued_at == issued_at))
    counts = defaultdict(int)
    for a in areas:
        sids, neighbor = mapping[a.id]
        simulated = any(stations[s].source.is_simulated for s in sids)
        ages = [(issued_at - latest[s][k + "_at"]).total_seconds() / 60
                for s in sids for k in ("rain", "wl") if s in latest and latest[s].get(k + "_at")]
        data_age = min(ages) if ages else None
        for h in range(0, 7):
            notes = [f"Dùng trạm lân cận ({len(sids)}) do khu vực chưa có trạm"] if neighbor and sids and a.level != "WARD" else []
            fh = [fc[s].get(max(h, 1)) for s in sids if fc[s].get(max(h, 1))]
            if any(f.is_cold_start for f in fh):
                notes.append("Có trạm dự báo cold-start (mượn dữ liệu trạm lân cận)")
            if h == 0:
                rains = [latest[s]["rain"] for s in sids if latest.get(s, {}).get("rain") is not None]
                wls = [latest[s]["wl"] / stations[s].flood_threshold_cm for s in sids
                       if latest.get(s, {}).get("wl") is not None]
            else:
                rains = [f.rainfall_mm for f in fh]
                wls = [f.water_level_cm / stations[f.station_id].flood_threshold_cm for f in fh
                       if f.water_level_cm is not None]
            prob = max((f.flood_probability for f in fh), default=None)
            ward, rain3 = a.level == "WARD", 0.0
            # phường không chịu triều: 0.0 (không phải None) để không đổi trọng số các đầu vào còn lại
            tide_ratio = tide[h] if a.id in exposed else 0.0 if ward else None
            if ward and fh:  # phường dùng độ cao và điểm ngập của chính phường
                seq = [max((fc[s][k].rainfall_mm for s in sids if fc[s].get(k)), default=0.0)
                       for k in range(max(h - 2, 1), max(h, 1) + 1)]
                rain3 = sum(seq)
                prob = round(flood_index.probability(flood_index.FloodInputs(
                    max(rains, default=0.0), rain3, tide_ratio, a.elevation_m, a.id in hot_wards,
                    a.id in severe)), 4)
            low = (a.elevation_m is not None and a.elevation_m < flood_index.LOW_ELEVATION_M) or a.id in hot_wards
            # mưa dông: quận theo điểm lưới của quận; phường chỉ khi thấp/có điểm ngập để vùng cảnh báo nhỏ lại
            storm_n = max((storm.get(s, 0) for s in sids), default=0) if h <= 3 and (low or not ward) else 0
            tide_d = flood_index.tide_depth_cm(tide_ratio) if a.id in exposed else 0.0
            rain_d = flood_index.rain_depth_cm(rain3) if low else 0.0
            reps = reports[a.id] if h <= 1 else []
            rep_d = max((flood_index.SEVERITY_CM.get(x.severity, 0) for x in reps if x.confirmations >= 1), default=0)
            conf = max((x.confirmations for x in reps), default=None)
            depth = max(tide_d, rain_d, rep_d)
            depth_cm = flood_index.round_depth(depth)
            rt, rr = flood_index.round_depth(tide_d), flood_index.round_depth(rain_d)
            cam = None
            if h <= 1:  # quận lấy camera của chính nó và của các phường con
                cam = max(cams[a.id] + [c["cam"] for c in kids[(a.id, h)] if c["cam"] is not None], default=None)
            cam_hi = cam is not None and cam >= cfg["overrides"]["camera_ratio_high"]
            # báo cáo chưa xác nhận (rep_d=0) không che nguyên nhân camera
            cause = ("REPORT" if reps and rep_d >= max(tide_d, rain_d) and not (cam_hi and not rep_d)
                     else "RAIN_TIDE" if rt and rr else "TIDE" if rt else "RAIN" if rr
                     else "CAMERA" if cam_hi
                     else "STORM" if storm_n >= cfg.get("storm_min_models", 2) else None)
            wards_info = {}
            if not ward:
                ch = kids[(a.id, h)]
                if ch:
                    top = max(ch, key=lambda c: c["depth"])
                    tide_ratio = max((c["tide"] for c in ch if c["exposed"] and c["tide"] is not None), default=0.0)
                    if top["depth_cm"] and top["depth"] > depth:
                        depth, depth_cm, cause = top["depth"], top["depth_cm"], top["cause"]
                    confs = [c["conf"] for c in ch if c["conf"]]  # báo cáo chưa xác nhận không nâng quận
                    conf = max(confs + ([conf] if conf is not None else []), default=None)
                    if not cause and any(c["cause"] == "REPORT" for c in ch):
                        cause = "REPORT"  # chỉ có báo cáo chưa xác nhận ở phường con
                    hit = [c["name"] for c in sorted(ch, key=lambda c: -c["depth"])
                           if c["depth_cm"] or (cause in ("CAMERA", "STORM") and c["cause"] == cause)]
                    wards_info = {"wards": hit[:MAX_WARD_NAMES], "wards_total": len(hit)}
                else:  # quận chưa có phường: chỉ đưa triều vào điểm số ở quận ven triều, không ước độ sâu
                    tide_ratio = tide[h] if a.name in TIDAL_DISTRICTS else 0.0
            inp = RiskInputs(
                flood_probability=prob,
                rainfall_mm=max(rains, default=None),
                water_level_ratio=max(wls, default=None),  # chỉ trạm đo thật
                camera_flood_ratio=cam,
                history_susceptibility=a.susceptibility,
                data_age_minutes=data_age, notes=notes, tide_ratio=tide_ratio,
                flood_depth_cm=depth if depth_cm else None, report_confirmations=conf,
                storm_models=storm_n or None)
            r = evaluate(inp, cfg, prev.get((a.id, h)))
            if ward:
                kids[(a.parent_id, h)].append({
                    "name": a.name, "depth": depth, "depth_cm": depth_cm, "conf": conf, "cause": cause,
                    "cam": cam, "tide": tide_ratio, "exposed": a.id in exposed, "level": r.level})
            counts[(h, r.level)] += 1
            db.add(FloodRiskSnapshot(
                area_id=a.id, issued_at=issued_at, horizon_h=h, risk_level=r.level, score=r.score,
                flood_probability=inp.flood_probability, rainfall_mm=inp.rainfall_mm,
                water_level_ratio=inp.water_level_ratio if inp.water_level_ratio is not None else inp.tide_ratio,
                camera_flood_ratio=inp.camera_flood_ratio,
                explanation={**r.explanation, "rule_version": rule.version if rule else 0,
                             "cause": cause, "depth_cm": depth_cm, **wards_info,
                             "stations": [stations[s].code for s in sids]},
                rule_id=rule.id if rule else None, is_simulated=simulated))
    db.commit()
    return {"areas": len(areas), "levels_now": {lv: counts[(0, lv)] for lv in
                                                ("LOW", "MEDIUM", "HIGH", "INSUFFICIENT_DATA")}}
