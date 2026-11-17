"""Thu thập dữ liệu thật từ Open-Meteo (CC BY 4.0, https://open-meteo.com).

- Mưa theo giờ: archive (tái phân tích ERA5/ECMWF IFS) + forecast API (mô hình số "best match").
- Mực nước biển/triều: Marine API `sea_level_height_msl` tại Vũng Tàu (m -> cm).
- Độ cao địa hình: Elevation API (Copernicus DEM 90 m).
Đây là dữ liệu MÔ HÌNH KHÍ TƯỢNG trên lưới, không phải trạm đo tại chỗ.
"""

import logging
import threading
import time
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.models import DataSource, MonitoringStation
from app.services.observation_service import upsert_observations

log = logging.getLogger("app.openmeteo")
FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
MARINE = "https://marine-api.open-meteo.com/v1/marine"
ELEVATION = "https://api.open-meteo.com/v1/elevation"
TIDE_POINT = (10.33, 107.08)  # cửa biển Vũng Tàu — triều ảnh hưởng hệ thống sông Sài Gòn–Đồng Nai
SOURCE_CODE = "OPEN_METEO"
TIDE_CODE = "OM-TIDE-VT"
TIDE_LAG_H = 4  # ngập đường ở TP.HCM trễ ~4 giờ (3-5) sau đỉnh triều Vũng Tàu, theo 7 tin báo chí
ELEVATION_BUDGET_S = 8


def _get(url: str, params: dict, tries: int = 3, timeout: float = 60) -> dict | list:
    for i in range(tries):
        try:
            r = httpx.get(url, params=params, timeout=timeout, headers={"User-Agent": get_settings().external_user_agent})
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError("unreachable")


def _series(item: dict, key: str) -> list[tuple[datetime, float]]:
    h = item["hourly"]
    return [(datetime.fromisoformat(t), v) for t, v in zip(h["time"], h[key], strict=True) if v is not None]


def fetch_rain(points: list[tuple[float, float]], start: datetime | None = None, end: datetime | None = None,
               past_days: int = 3) -> list[list[tuple[datetime, float]]]:
    """Mưa giờ (UTC) cho nhiều điểm; start/end -> archive, ngược lại forecast API (past_days + 1 ngày tới)."""
    params = {"latitude": ",".join(f"{p[0]:.4f}" for p in points),
              "longitude": ",".join(f"{p[1]:.4f}" for p in points), "hourly": "precipitation", "timezone": "GMT"}
    if start:
        url = ARCHIVE
        params |= {"start_date": f"{start:%Y-%m-%d}", "end_date": f"{end:%Y-%m-%d}"}
    else:
        url = FORECAST
        params |= {"past_days": past_days, "forecast_days": 1}
    data = _get(url, params)
    data = data if isinstance(data, list) else [data]
    return [_series(d, "precipitation") for d in data]


STORM_MODELS = ("ecmwf_ifs025", "gfs_seamless", "icon_seamless", "jma_seamless", "cma_grapes_global",
                "ukmo_seamless", "meteofrance_seamless")
STORM_MM_3H = 10.0  # >= 2/7 mô hình cùng báo: recall 8/20 trận ngập do mưa, báo 4,7% ngày-quận (experiment_convective)


def storm_model_counts(points: list[tuple[float, float]], issued_at: datetime) -> list[int]:
    """Mỗi điểm: số mô hình dự báo tổng mưa 3 giờ tới (issued_at, issued_at+3h] >= STORM_MM_3H."""
    params = {"latitude": ",".join(f"{p[0]:.4f}" for p in points),
              "longitude": ",".join(f"{p[1]:.4f}" for p in points), "hourly": "precipitation",
              "models": ",".join(STORM_MODELS), "forecast_days": 2, "timezone": "GMT"}
    data = _get(FORECAST, params, timeout=30)
    data = data if isinstance(data, list) else [data]
    window = {issued_at + timedelta(hours=k) for k in (1, 2, 3)}  # mưa giờ t là lượng của giờ kết thúc tại t
    out = []
    for item in data:
        hours = [datetime.fromisoformat(t) in window for t in item["hourly"]["time"]]
        out.append(sum(
            sum(v or 0.0 for v, w in zip(item["hourly"].get(f"precipitation_{m}", []), hours, strict=False) if w)
            >= STORM_MM_3H for m in STORM_MODELS))
    return out


def fetch_tide(start: datetime | None = None, end: datetime | None = None, past_days: int = 3):
    params = {"latitude": TIDE_POINT[0], "longitude": TIDE_POINT[1], "hourly": "sea_level_height_msl", "timezone": "GMT"}
    params |= ({"start_date": f"{start:%Y-%m-%d}", "end_date": f"{end:%Y-%m-%d}"} if start
               else {"past_days": past_days, "forecast_days": 1})
    return [(t, round(v * 100, 1)) for t, v in _series(_get(MARINE, params), "sea_level_height_msl")]


_elev_cache: dict[tuple[float, float], float] = {}
_elev_lock = threading.Lock()


def elevations(coords: list[tuple[float, float]]) -> list[float | None]:
    """Độ cao (m) cho danh sách (lat, lon); làm tròn ~100 m để cache."""
    keys = [(round(la, 3), round(lo, 3)) for la, lo in coords]
    with _elev_lock:
        if len(_elev_cache) > 200_000:  # chặn cache tăng vô hạn; xoá trước khi tính phần thiếu
            _elev_cache.clear()
    missing = list(dict.fromkeys(k for k in keys if k not in _elev_cache))
    deadline = time.monotonic() + ELEVATION_BUDGET_S  # hàm này chạy trong request công khai
    for i in range(0, len(missing), 100):
        if time.monotonic() > deadline:
            log.warning("Hết thời gian tra độ cao; %d điểm dùng None", len(missing) - i)
            break
        chunk = missing[i:i + 100]
        try:
            d = _get(ELEVATION, {"latitude": ",".join(str(k[0]) for k in chunk),
                                 "longitude": ",".join(str(k[1]) for k in chunk)}, tries=1, timeout=5)
        except (httpx.HTTPError, ValueError):
            log.warning("Elevation API lỗi; bỏ qua độ cao cho %d điểm", len(chunk))
            continue
        with _elev_lock:
            for k, e in zip(chunk, d.get("elevation", []), strict=False):
                _elev_cache[k] = e
    return [_elev_cache.get(k) for k in keys]


# ------------------------------------------------------------------ DB
def source(db: Session) -> DataSource:
    src = db.scalar(select(DataSource).where(DataSource.code == SOURCE_CODE))
    if not src:
        src = DataSource(code=SOURCE_CODE, name="Open-Meteo (mô hình khí tượng/hải văn)", kind="OPEN_DATA",
                         is_simulated=False, license="CC BY 4.0", url="https://open-meteo.com",
                         description="Mưa giờ tái phân tích + dự báo số trên lưới; mực nước biển Marine API; DEM 90 m. "
                                     "Không phải trạm đo tại chỗ.")
        db.add(src)
        db.flush()
    return src


def stations(db: Session) -> tuple[list[MonitoringStation], MonitoringStation | None]:
    src = source(db)
    sts = list(db.scalars(select(MonitoringStation).where(MonitoringStation.source_id == src.id,
                                                          MonitoringStation.deleted_at.is_(None))))
    return [s for s in sts if s.station_type == "RAIN"], next((s for s in sts if s.code == TIDE_CODE), None)


def _store(db: Session, rain_sts, rain_series, tide_st, tide_series, until: datetime) -> int:
    src = source(db)
    rows = []
    for st, ser in zip(rain_sts, rain_series, strict=True):
        rows += [{"station_id": st.id, "observed_at": t, "rainfall_mm": float(v), "source_id": src.id}
                 for t, v in ser if t <= until]
    if tide_st:
        rows += [{"station_id": tide_st.id, "observed_at": t, "water_level_cm": float(v), "source_id": src.id}
                 for t, v in tide_series if t <= until]
    n = upsert_observations(db, rows)
    db.commit()
    return n


def ingest_history(db: Session, days: int = 730, log_fn=print) -> int:
    rain_sts, tide_st = stations(db)
    end = utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    total = 0
    t = start
    while t < end:  # chia khối 180 ngày cho request vừa phải
        t2 = min(t + timedelta(days=180), end)
        rain = fetch_rain([(s.latitude, s.longitude) for s in rain_sts], t, t2)
        tide = fetch_tide(t, t2) if tide_st else []
        total += _store(db, rain_sts, rain, tide_st, tide, end)
        log_fn(f"      Open-Meteo {t:%Y-%m-%d} → {t2:%Y-%m-%d}: tổng {total} bản ghi")
        t = t2 + timedelta(hours=1)
    return total


_forecast_cache: dict = {"at": None, "rain": {}, "tide": []}


def ingest_latest(db: Session) -> int:
    """Gọi mỗi chu kỳ: ghi các giờ đã qua làm quan trắc; giữ dự báo số giờ tới trong bộ nhớ."""
    rain_sts, tide_st = stations(db)
    if not rain_sts:
        return 0
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    rain = fetch_rain([(s.latitude, s.longitude) for s in rain_sts])
    tide = fetch_tide() if tide_st else []
    _forecast_cache.update(at=now, rain={s.id: [(t, v) for t, v in ser if t > now] for s, ser in zip(rain_sts, rain,
                                                                                                    strict=True)},
                           tide=[(t, v) for t, v in tide if t > now])
    return _store(db, rain_sts, rain, tide_st, tide, now)


_tide_stats: dict = {}


def tide_stats(db: Session) -> tuple[float, float] | None:
    """(P50, P95) mực nước biển 1 năm gần nhất (cm), cache theo ngày."""
    from app.models import WaterLevelObservation

    key = utcnow().date()
    if _tide_stats.get("key") == key:
        return _tide_stats["v"]
    st = db.scalar(select(MonitoringStation).where(MonitoringStation.code == TIDE_CODE))
    if not st:
        return None
    vals = sorted(v for (v,) in db.execute(select(WaterLevelObservation.water_level_cm).where(
        WaterLevelObservation.station_id == st.id,
        WaterLevelObservation.observed_at >= utcnow() - timedelta(days=365))) if v is not None)
    v = (vals[len(vals) // 2], vals[int(len(vals) * 0.95)]) if len(vals) > 100 else None
    _tide_stats.update(key=key, v=v)
    return v


def tide_ratio(tide_cm: float | None, stats: tuple[float, float] | None) -> float | None:
    """(triều − P50)/(P95 − P50): 0 = triều trung bình, 1 = mức triều cường thường gặp."""
    if tide_cm is None or not stats or stats[1] <= stats[0]:
        return None
    return round((tide_cm - stats[0]) / (stats[1] - stats[0]), 3)


def tide_at(db: Session, t: datetime) -> float | None:
    """Triều ảnh hưởng ngập tại t = triều Vũng Tàu lúc t − TIDE_LAG_H (Marine, không có thì quan trắc)."""
    from app.models import WaterLevelObservation

    t = t - timedelta(hours=TIDE_LAG_H)
    for ft, v in _forecast_cache.get("tide", []):
        if ft == t:
            return v
    st = db.scalar(select(MonitoringStation).where(MonitoringStation.code == TIDE_CODE))
    if not st:
        return None
    return db.scalar(select(WaterLevelObservation.water_level_cm).where(
        WaterLevelObservation.station_id == st.id, WaterLevelObservation.observed_at <= t)
        .order_by(WaterLevelObservation.observed_at.desc()).limit(1))


def nwp_forecast() -> dict:
    """Dự báo số Open-Meteo giờ tới {'rain': {station_id: [(t, mm)]}, 'tide': [(t, cm)]} — để tham chiếu/triều."""
    return _forecast_cache
