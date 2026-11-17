"""Điều phối suy luận LSTM/GRU cho mọi trạm, xử lý cold-start, lưu bảng forecasts."""

import logging
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.forecasting import inference
from app.ai.forecasting.preprocessing import HORIZON, LOOKBACK, quality_of
from app.models import AdministrativeArea, Forecast, ModelVersion, MonitoringStation
from app.repositories import observations as obs_repo
from app.services import flood_index, gis_service
from app.services import openmeteo_service as om

log = logging.getLogger("app.forecast")
MAX_MISSING_FOR_OWN_DATA = 0.5


def active_model(db: Session) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True),
                                                ModelVersion.model_type.in_(["LSTM", "GRU"])).limit(1))


def cluster_models(db: Session) -> dict[str, ModelVersion]:
    """Mô hình cụm đang hoạt động, chỉ khi tinh chỉnh từ chính mô hình gốc đang dùng; nhiều bản -> lấy bản mới nhất."""
    base = active_model(db)
    if not base:
        return {}
    mvs = db.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True),
                                                ModelVersion.model_type.in_(["LSTM_CLUSTER", "GRU_CLUSTER"]))
                     .order_by(ModelVersion.id))  # id tăng dần: bản sau ghi đè bản trước
    out = {}
    for m in mvs:
        p = m.params or {}
        try:
            ok = int(p["base_model_id"]) == base.id
        except (KeyError, TypeError, ValueError):
            ok = False
        if ok and p.get("cluster") and m.artifact_path:
            out[p["cluster"]] = m
    return out


def run_inference(db: Session, issued_at: datetime | None = None) -> dict:
    mv = active_model(db)
    if not mv:
        return {"status": "NO_MODEL", "count": 0}
    lm = inference.load(mv.artifact_path)
    issued_at = issued_at or obs_repo.latest_time(db)
    if not issued_at:
        return {"status": "NO_DATA", "count": 0}
    stations = list(db.scalars(select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None),
                                                               MonitoringStation.status == "ACTIVE")))
    start = issued_at - timedelta(hours=LOOKBACK + 12)
    tide_st = next((s for s in stations if s.code == om.TIDE_CODE), None)
    tstats = om.tide_stats(db)
    tide_df = obs_repo.series(db, tide_st.id, start, issued_at)[["time", "water_level_cm"]] if tide_st else None
    if tide_st and "wl" not in lm.heads:
        stations = [s for s in stations if s.id != tide_st.id]  # mô hình chỉ dự báo mưa
    thresholds: dict[int, float] = {}
    windows: dict[int, tuple] = {}
    for st in stations:
        df = obs_repo.series(db, st.id, start, issued_at)
        df = df[["time", "rain_mm", "water_level_cm"]]
        thresholds[st.id] = st.flood_threshold_cm
        if df["water_level_cm"].isna().all() and tide_df is not None and tstats:
            # điểm lưới mưa: đặc trưng mực nước = triều chung, như lúc huấn luyện
            df = df.drop(columns="water_level_cm").merge(tide_df, on="time", how="outer")
            thresholds[st.id] = tstats[1]
        prep = inference.prepare_window(_pad_to(df, issued_at), thresholds[st.id], lm.scaler)
        last = st.last_observation_at
        age_h = (issued_at - last).total_seconds() / 3600 if last else 999
        if prep and prep[1] <= MAX_MISSING_FOR_OWN_DATA:
            windows[st.id] = (prep[0], quality_of(prep[1], age_h), False)

    # Cold-start: trạm mới/thiếu dữ liệu mượn chuỗi trạm lân cận cùng cụm đã có dữ liệu
    # Tự rời cold-start khi dữ liệu riêng phủ hơn nửa lookback (MAX_MISSING_FOR_OWN_DATA).
    areas = gis_service.area_geometries(db)
    cluster_of = {s.id: _cluster(areas, s.area_id) for s in stations}
    donor_info: dict[str, dict] = {}
    for st in stations:
        if st.id in windows:
            continue
        near = [sid for sid, _ in gis_service.nearest_stations(db, st.longitude, st.latitude, 6, 15000)
                if sid in windows and not windows[sid][2]]
        donors = order_donors(near, cluster_of, cluster_of.get(st.id))
        if donors:
            windows[st.id] = (windows[donors[0]][0], "POOR", True)
            donor_info[st.code] = {"donor": next((s.code for s in stations if s.id == donors[0]), None),
                                   "same_cluster":
                                   bool(cluster_of[st.id]) and cluster_of[donors[0]] == cluster_of[st.id]}

    if not windows:
        return {"status": "NO_DATA", "count": 0}
    ids = list(windows)
    by_id = {s.id: s for s in stations}
    # Trạm (kể cả cold-start, dùng cụm của chính nó) dùng mô hình cụm nếu có, ngược lại mô hình gốc.
    group_of: dict[int, tuple] = {}
    cms = cluster_models(db)
    for i in ids:
        cm = cms.get(cluster_of.get(i, ""))
        try:
            group_of[i] = (cm, inference.load(cm.artifact_path)) if cm else (mv, lm)
        except Exception:
            log.warning("Không nạp được mô hình cụm %s, dùng mô hình gốc", cm.name, exc_info=True)
            group_of[i] = (mv, lm)
    model_of: dict[int, ModelVersion] = {}
    pred_of: dict[int, list] = {}
    for gmv in {g[0].id: g[0] for g in group_of.values()}.values():
        gids = [i for i in ids if group_of[i][0].id == gmv.id]
        glm = group_of[gids[0]][1]
        X = np.concatenate([windows[i][0] for i in gids])
        preds = inference.predict(glm, X, [thresholds.get(i, by_id[i].flood_threshold_cm) for i in gids])
        if preds and preds[0][0]["flood_probability"] is None:
            _estimate_flood(db, issued_at, [by_id[i] for i in gids], preds, tstats)
        for i, p in zip(gids, preds, strict=True):
            model_of[i], pred_of[i] = gmv, p

    db.execute(delete(Forecast).where(Forecast.issued_at == issued_at, Forecast.station_id.in_(ids)))
    for sid in ids:
        pts, st = pred_of[sid], by_id[sid]
        _, quality, cold = windows[sid]
        for p in pts:
            db.add(Forecast(station_id=sid, area_id=st.area_id, model_version_id=model_of[sid].id, issued_at=issued_at,
                            horizon_h=p["horizon_h"], target_time=issued_at + timedelta(hours=p["horizon_h"]),
                            rainfall_mm=p["rainfall_mm"],
                            water_level_cm=p["water_level_cm"] if st.station_type != "RAIN" else None,
                            flood_probability=p["flood_probability"], data_quality=quality,
                            is_cold_start=cold, is_simulated=st.source.is_simulated))
    db.commit()
    return {"status": "OK", "count": len(ids), "issued_at": issued_at, "model": f"{mv.name}:{mv.version}",
            "cluster_models": sorted({f"{m.name}:{m.version}" for m in model_of.values() if m.id != mv.id}),
            "cold_start": [by_id[i].code for i in ids if windows[i][2]], "cold_start_donors": donor_info}


def _cluster(areas: dict, area_id: int | None) -> str:
    a = areas.get(area_id) if area_id else None
    if a and not a["cluster"] and a["parent_id"]:  # phường thừa hưởng cụm của quận
        a = areas.get(a["parent_id"])
    return a["cluster"] if a else ""


def order_donors(near: list[int], cluster_of: dict[int, str], mine: str | None) -> list[int]:
    """Trạm cùng cụm lên trước; giữ thứ tự khoảng cách trong mỗi nhóm. Không có cụm -> thứ tự khoảng cách."""
    if not mine:
        return near
    return sorted(near, key=lambda sid: cluster_of.get(sid) != mine)  # sorted ổn định


def _estimate_flood(db: Session, issued_at: datetime, stations, preds, tstats) -> None:
    """Chưa có nhãn ngập thật -> xác suất ngập = chỉ số ước tính từ mưa dự báo + triều + địa hình + điểm ngập."""
    from app.models import FloodHotspot

    hot_areas = set(db.scalars(select(FloodHotspot.area_id).distinct()))
    hot_areas |= set(db.scalars(select(AdministrativeArea.parent_id).where(AdministrativeArea.id.in_(hot_areas))))
    tides = {h: om.tide_ratio(om.tide_at(db, issued_at + timedelta(hours=h)), tstats) for h in range(1, 7)}
    for st, pts in zip(stations, preds, strict=True):
        recent = obs_repo.series(db, st.id, issued_at - timedelta(hours=2), issued_at)["rain_mm"].fillna(0).tolist()
        rain = recent[-2:] + [p["rainfall_mm"] for p in pts]
        for k, p in enumerate(pts):
            i = len(rain) - len(pts) + k
            x = flood_index.FloodInputs(p["rainfall_mm"], sum(rain[max(0, i - 2): i + 1]), tides[p["horizon_h"]],
                                        st.elevation_m, st.area_id in hot_areas)
            p["flood_probability"] = round(flood_index.probability(x), 4)


def _pad_to(df, issued_at):
    """Đảm bảo lưới thời gian kết thúc tại issued_at (thiếu bản ghi cuối -> missing, không bịa)."""
    import pandas as pd

    if df.empty or df["time"].max() < issued_at:
        df = pd.concat([df, pd.DataFrame({"time": [issued_at], "rain_mm": [None], "water_level_cm": [None]})])
    return df.sort_values("time").reset_index(drop=True)


def station_forecast(db: Session, station_id: int, issued_at: datetime | None = None):
    issued_at = issued_at or db.scalar(select(Forecast.issued_at).where(Forecast.station_id == station_id)
                                       .order_by(Forecast.issued_at.desc()).limit(1))
    if not issued_at:
        return []
    return list(db.scalars(select(Forecast).where(Forecast.station_id == station_id, Forecast.issued_at == issued_at)
                           .order_by(Forecast.horizon_h)))


assert HORIZON == 6
