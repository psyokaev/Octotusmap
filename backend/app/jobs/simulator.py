"""DEMO_MODE: sinh dữ liệu MÔ PHỎNG nối tiếp tới giờ hiện tại + khung hình camera mô phỏng.

Mọi bản ghi tạo ở đây có is_simulated=True và nguồn SIMULATED.
"""

from datetime import timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.computer_vision.synthetic import camera_frame
from app.ai.forecasting.synthetic import simulate_network
from app.core.database import utcnow
from app.gis.demo_catalog import CAMERAS, STATIONS
from app.models import Camera, DataSource, MonitoringStation, WaterLevelObservation
from app.services import camera_service
from app.services.observation_service import rain_flag, upsert_observations, wl_flag

SEED = 2026
FAULT_RATE = 0.008  # tỉ lệ mất bản ghi mô phỏng lỗi truyền
SPIKE_RATE = 0.001  # tỉ lệ giá trị bất thường mô phỏng lỗi cảm biến
HISTORY_DAYS = 120


def _params():
    return {c: dict(code=c, lat=lat, lon=lon, threshold_cm=thr, sensitivity=s, tide_amp=a, base_cm=b)
            for c, _n, _t, _ad, lat, lon, thr, s, a, b in STATIONS}


def ingest_until_now(db: Session, history_days: int = HISTORY_DAYS) -> int:
    src = db.scalar(select(DataSource).where(DataSource.code == "SIMULATED"))
    params = _params()
    stations = [s for s in db.scalars(select(MonitoringStation).where(
        MonitoringStation.source_id == src.id, MonitoringStation.deleted_at.is_(None))) if s.code in params]
    if not stations:
        return 0
    now_h = utcnow().replace(minute=0, second=0, microsecond=0)
    last = db.scalar(select(func.max(WaterLevelObservation.observed_at)).where(
        WaterLevelObservation.station_id.in_([s.id for s in stations])))
    start = (last + timedelta(hours=1)) if last else now_h - timedelta(days=history_days)
    if start > now_h:
        return 0
    sim = simulate_network([params[s.code] for s in stations], start, now_h + timedelta(hours=1), SEED)
    rng = np.random.default_rng(int(start.timestamp()))
    rows = []
    for st in stations:
        s = sim[st.code]
        prev = None
        for t, r, w in zip(s["time"], s["rain"], s["wl"], strict=True):
            row = {"station_id": st.id, "observed_at": t, "is_simulated": True, "source_id": src.id}
            if rng.random() < FAULT_RATE:
                continue  # mất bản ghi (không bịa giá trị thay thế)
            w = float(w) + (400 if rng.random() < SPIKE_RATE else 0)
            if st.station_type in ("RAIN", "COMBINED"):
                row["rainfall_mm"] = float(r)
                row["rain_quality"] = rain_flag(float(r))
            if st.station_type in ("WATER_LEVEL", "COMBINED"):
                row["water_level_cm"] = w
                row["wl_quality"] = wl_flag(w, prev)
                prev = w if row["wl_quality"] == "VALID" else prev
            rows.append(row)
    n = upsert_observations(db, rows)
    db.commit()
    return n


def simulate_cameras(db: Session) -> int:
    """Khung hình DEMO: mực nước vẽ trong ảnh suy từ trạm tham chiếu; phát hiện bằng model thật."""
    from app.repositories.observations import latest_values

    ref = {c: s for c, _n, _la, _lo, s, _p in CAMERAS}
    stations = {s.code: s for s in db.scalars(select(MonitoringStation))}
    latest = latest_values(db, [s.id for s in stations.values()])
    tick = int(utcnow().timestamp() // 300)
    n = 0
    for cam in db.scalars(select(Camera).where(Camera.deleted_at.is_(None), Camera.status == "ACTIVE")):
        st = stations.get(ref.get(cam.code, ""))
        if not st or not cam.source.is_simulated:
            continue
        wl = latest.get(st.id, {}).get("wl")
        if wl is None:
            continue
        level = float(np.clip((wl - (st.flood_threshold_cm - 20)) / 60, 0, 0.9))
        camera_service.analyze(db, camera_frame(cam.code, level, tick), cam, None, is_simulated=True)
        n += 1
    return n
