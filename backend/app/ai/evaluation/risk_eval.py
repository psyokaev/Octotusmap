"""Đánh giá Accuracy/F1 của điều kiện độ sâu ước tính >= 20 cm (triều lệch 4 h + mưa) với sự kiện ngập báo chí.

Triều và mưa là dữ liệu mô hình Open-Meteo, không phải trạm đo. Chỉ đánh giá điều kiện độ sâu ước tính,
KHÔNG phải toàn bộ rule engine (điểm số, xác suất, hysteresis, báo cáo, camera). Lõi nhận dữ liệu thuần;
chỉ `load_inputs` chạm DB.
"""

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.ai.evaluation.metrics import classification_metrics
from app.services import flood_index

VN = timedelta(hours=7)
CAUSES = {"ALL": {"TIDE", "RAIN", "RAIN_TIDE"}, "TIDE": {"TIDE", "RAIN_TIDE"}, "RAIN": {"RAIN", "RAIN_TIDE"}}
CALIBRATION_DATES = {date(2026, 10, 10), date(2026, 10, 27), date(2026, 10, 28)}
PERIOD = (date(2025, 9, 1), date(2026, 11, 9))
NOTE = ("Nhãn âm là GIẢ ĐỊNH (không có tin báo chí = không ngập): "
        "precision bị đánh giá thấp, accuracy bị ngày âm chi phối, đọc F1. "
        "Triều và mưa là dữ liệu mô hình Open-Meteo, không phải trạm đo; "
        "chỉ đánh giá điều kiện độ sâu ước tính >= 20 cm, "
        "không phải toàn bộ rule engine (điểm số, xác suất, hysteresis, báo cáo, camera). "
        "Tập held-out gồm các đợt triều cường sát ngày hiệu chỉnh (2026-10-11, 2026-10-26). "
        "Baseline quy tắc cũ báo cả 24 quận nên một phần cải thiện đến từ việc giới hạn theo quận.")


def vn_date(ts: datetime) -> date:
    return (ts + VN).date()


def truth_units(events, districts: set[int], start: date, end: date, cause_set: set[str]):
    """events: (quận|None, started_at UTC, cause). Trả (tập (quận, ngày) dương, số sự kiện thiếu quận bị bỏ)."""
    pos, skipped = set(), 0
    for d, t, cause in events:
        if d is None:
            skipped += 1
        elif d in districts and cause in cause_set and start <= vn_date(t) <= end:
            pos.add((d, vn_date(t)))
    return pos, skipped


def _days(index: pd.DatetimeIndex) -> set[date]:
    return {i.date() for i in index + VN}


def tide_days(level: pd.Series, stats, tide_ratio, lag_h: int, thr_cm: float):
    """level: mực triều Vũng Tàu theo giờ (index UTC). Trả (ngày độ sâu ước tính >= thr, ngày tỉ số không lệch >= 1)."""
    ratio = level.map(lambda v: tide_ratio(v, stats))
    lagged = ratio.copy()
    lagged.index = lagged.index + pd.Timedelta(hours=lag_h)  # r(t) dùng mực tại t - lag
    new = _days(lagged.index[lagged.map(lambda r: flood_index.tide_depth_cm(r) >= thr_cm).astype(bool)])
    old = _days(ratio.index[ratio.map(lambda r: r is not None and r == r and r >= 1.0).astype(bool)])
    return new, old


def rain_days(rain: pd.Series, thr_cm: float) -> set[date]:
    r3 = rain.sort_index().asfreq("h").rolling(3, min_periods=1).sum()
    return _days(r3.index[r3.map(lambda v: v == v and flood_index.rain_depth_cm(v) >= thr_cm).astype(bool)])


def predictions(districts, tide_exposed, rain_capable, rain_series, tide_new, tide_old, thr_cm):
    """Tập (quận, ngày) dự báo dương theo nhóm ALL/TIDE/RAIN và baseline quy tắc cũ (mọi quận)."""
    tide = {(d, day) for d in districts if d in tide_exposed for day in tide_new}
    rain = {(d, day) for d in districts if d in rain_capable and d in rain_series
            for day in rain_days(rain_series[d], thr_cm)}
    old = {(d, day) for d in districts for day in tide_old}
    return {"TIDE": tide, "RAIN": rain, "ALL": tide | rain}, old


def score(truth: set, pred: set, districts, days: list[date], city: bool) -> dict:
    if city:
        units = [(0, day) for day in days]
        truth, pred = {(0, d) for _, d in truth}, {(0, d) for _, d in pred}
    else:
        units = [(d, day) for d in sorted(districts) for day in days]
    yt = np.array([u in truth for u in units], float)
    yp = np.array([u in pred for u in units], float)
    m = classification_metrics(yt, yp, 0.5)
    return {"n": len(units), "positives": int(yt.sum()), "accuracy": m["accuracy"], "precision": m["precision"],
            "recall": m["recall"], "f1": m["f1"], **m["confusion_matrix"]}


def evaluate(events, districts, tide_exposed, rain_capable, rain_series, level, stats, tide_ratio, *,
             lag_h=4, thr_cm=20.0, period=PERIOD, calib=CALIBRATION_DATES) -> dict:
    districts = set(districts)
    start, end = period
    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    split = {"held_out": [d for d in all_days if d not in calib], "calibration": [d for d in all_days if d in calib]}
    tide_new, tide_old = tide_days(level, stats, tide_ratio, lag_h, thr_cm)
    pred, old = predictions(districts, tide_exposed, rain_capable, rain_series, tide_new, tide_old, thr_cm)
    out = {"note": NOTE, "period": [str(start), str(end)], "lag_h": lag_h, "calibration_dates": sorted(map(str, calib)),
           "skipped_null_area_events": truth_units(events, districts, start, end, CAUSES["ALL"])[1]}
    for sp, days in split.items():
        for g, cs in CAUSES.items():
            truth = truth_units(events, districts, start, end, cs)[0]
            for city in (False, True):
                out[f"{sp}/{g}/{'city-day' if city else 'district-day'}"] = score(truth, pred[g], districts, days, city)
        for g in ("ALL", "TIDE"):
            truth = truth_units(events, districts, start, end, CAUSES[g])[0]
            out[f"{sp}/old_rule_vs_{g}/district-day"] = score(truth, old, districts, days, False)
    return out


def load_inputs(db, period=PERIOD):
    """Đọc DB (chỉ SELECT) -> tham số của `evaluate`."""
    from sqlalchemy import select

    from app.models import (
        AdministrativeArea,
        FloodHotspot,
        HistoricalFloodEvent,
        MonitoringStation,
        RainfallObservation,
        WaterLevelObservation,
    )
    from app.services import openmeteo_service as om
    from app.services import risk_service
    from app.services.rule_engine import DEFAULT_RULE_CONFIG

    areas = {a.id: a for a in db.scalars(select(AdministrativeArea))}
    dist_of = {a.id: (a.id if a.level == "DISTRICT" else a.parent_id) for a in areas.values()}
    districts = {a.id for a in areas.values() if a.level == "DISTRICT"}
    exposed = {dist_of[w] for w in risk_service.tide_exposed_wards(db) if w in dist_of}
    capable = {dist_of[a.id] for a in areas.values() if a.level == "WARD" and a.elevation_m is not None
               and a.elevation_m < flood_index.LOW_ELEVATION_M and dist_of[a.id]}
    capable |= {dist_of[h] for h in db.scalars(select(FloodHotspot.area_id).where(FloodHotspot.area_id.is_not(None)))
                if h in dist_of}
    lo = datetime.combine(period[0], datetime.min.time()) - VN - timedelta(days=1)
    hi = datetime.combine(period[1], datetime.min.time()) + timedelta(days=2)
    tide_st = db.scalar(select(MonitoringStation).where(MonitoringStation.code == om.TIDE_CODE))
    rows = db.execute(select(WaterLevelObservation.observed_at, WaterLevelObservation.water_level_cm).where(
        WaterLevelObservation.station_id == tide_st.id, WaterLevelObservation.is_simulated.is_(False),
        WaterLevelObservation.quality_flag == "VALID",
        WaterLevelObservation.observed_at.between(lo, hi))).all()
    level = pd.Series({t: v for t, v in rows if v is not None}, dtype=float).sort_index()
    rain: dict[int, pd.Series] = {}
    for st in db.scalars(select(MonitoringStation).where(MonitoringStation.station_type == "RAIN")):
        d = dist_of.get(st.area_id)
        if d is None:
            continue
        rr = db.execute(select(RainfallObservation.observed_at, RainfallObservation.rainfall_mm).where(
            RainfallObservation.station_id == st.id, RainfallObservation.is_simulated.is_(False),
            RainfallObservation.quality_flag == "VALID",
            RainfallObservation.observed_at.between(lo, hi))).all()
        s = pd.Series({t: v for t, v in rr if v is not None}, dtype=float)
        rain[d] = s if d not in rain else pd.concat([rain[d], s]).groupby(level=0).max()  # nhiều trạm: lấy lớn nhất
    events = [(dist_of.get(e.area_id) if e.area_id else None, e.started_at, e.cause)
              for e in db.scalars(select(HistoricalFloodEvent).where(HistoricalFloodEvent.is_simulated.is_(False)))]
    stats = om.tide_stats(db)
    if not stats:
        raise SystemExit("Chưa có thống kê triều")
    return dict(events=events, districts=districts, tide_exposed=exposed, rain_capable=capable, rain_series=rain,
                level=level, stats=stats, tide_ratio=om.tide_ratio, lag_h=om.TIDE_LAG_H,
                thr_cm=float(DEFAULT_RULE_CONFIG["overrides"].get("flood_depth_cm_high", 20)))
