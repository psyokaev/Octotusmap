"""LSTM xác suất "quận có ngập trong 6 giờ tới" (scripts/experiment_flood_district.py huấn luyện).

Một module cho cả huấn luyện và dự báo để đặc trưng giống hệt nhau. Chỉ để HIỂN THỊ: không vào luật cảnh báo.
Đặc trưng mỗi giờ: log1p(mưa), tỉ lệ triều đã lệch TIDE_LAG_H, sin/cos giờ VN, độ cao/20, có điểm ngập, quận ven triều.
"""

import json
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

LOOKBACK, HORIZON = 24, 6
MODEL_TYPE = "LSTM_FLOOD"
VN = timedelta(hours=7)
_cache: dict[str, tuple] = {}


def features(rain: np.ndarray, idx: pd.DatetimeIndex, tide_ratio: np.ndarray, elevation_m: float | None,
             hotspot: bool, tidal: bool) -> np.ndarray:
    hour = (idx + VN).hour.to_numpy()
    static = [min((elevation_m or 10) / 20, 1.5), float(hotspot), float(tidal)]
    return np.column_stack([np.log1p(np.clip(rain, 0, None)), np.clip(tide_ratio, -2, 2),
                            np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24),
                            np.tile(static, (len(idx), 1))]).astype(np.float32)


def build(cell: str, n_feat: int, units: int = 32):
    import keras

    rnn = keras.layers.GRU if cell == "gru" else keras.layers.LSTM
    m = keras.Sequential([keras.Input((LOOKBACK, n_feat)), rnn(units), keras.layers.Dropout(0.2),
                          keras.layers.Dense(16, activation="relu"), keras.layers.Dense(1, activation="sigmoid")])
    m.compile(optimizer=keras.optimizers.Adam(1e-3), loss="binary_crossentropy",
              metrics=[keras.metrics.AUC(curve="PR", name="pr_auc")])
    return m


def calibrate(p: np.ndarray, a: float, b: float) -> np.ndarray:
    """Platt: class weight làm xác suất thô phồng lên; đưa về tần suất thật học trên validation."""
    z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    return 1 / (1 + np.exp(-(a * z + b)))


def save(model, out_dir: Path, a: float, b: float, meta: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save(out_dir / "model.keras")
    (out_dir / "meta.json").write_text(json.dumps({"platt": [a, b], **meta}, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return out_dir


def _load(path: str):
    if path not in _cache:
        import keras

        meta = json.loads((Path(path) / "meta.json").read_text(encoding="utf-8"))
        _cache.clear()  # chỉ giữ mô hình đang dùng
        _cache[path] = (keras.models.load_model(Path(path) / "model.keras", compile=False), meta)
    return _cache[path]


def predict(db, issued_at) -> dict[int, float]:
    """{quận: xác suất đã hiệu chỉnh có ngập trong 6 giờ sau issued_at}. Không có mô hình -> {}."""
    from sqlalchemy import select

    from app.ai.forecasting.flood_labels import district_of
    from app.models import AdministrativeArea, FloodHotspot, ModelVersion, MonitoringStation, RainfallObservation
    from app.models import WaterLevelObservation as W
    from app.services import openmeteo_service as om
    from app.services.risk_service import TIDAL_DISTRICTS

    mv = db.scalar(select(ModelVersion).where(ModelVersion.model_type == MODEL_TYPE, ModelVersion.is_active.is_(True)))
    if not mv or not Path(mv.artifact_path).exists():
        return {}
    model, meta = _load(mv.artifact_path)
    idx = pd.date_range(end=issued_at, periods=LOOKBACK, freq="h")
    tide_st = db.scalar(select(MonitoringStation).where(MonitoringStation.code == om.TIDE_CODE))
    tstats = om.tide_stats(db)
    lag = idx - timedelta(hours=om.TIDE_LAG_H)
    tv = (pd.Series(dict(db.execute(select(W.observed_at, W.water_level_cm).where(
        W.station_id == tide_st.id, W.observed_at >= lag[0] - timedelta(hours=6), W.observed_at <= lag[-1])).all()))
          if tide_st else pd.Series(dtype=float))
    tv = tv.sort_index().reindex(tv.index.union(lag)).ffill().reindex(lag).to_numpy() if len(tv) else np.full(
        LOOKBACK, np.nan)
    ratio = np.array([om.tide_ratio(None if math.isnan(v) else float(v), tstats) or 0.0 for v in tv], np.float32)
    areas = {a.id: (a.level, a.parent_id) for a in db.scalars(select(AdministrativeArea))}
    names = {a.id: a.name for a in db.scalars(select(AdministrativeArea).where(AdministrativeArea.level == "DISTRICT"))}
    hot = set(db.scalars(select(FloodHotspot.area_id).distinct()))
    hot |= {areas[h][1] for h in hot if h in areas and areas[h][1]}
    X, ids = [], []
    for s in db.scalars(select(MonitoringStation).where(MonitoringStation.code.like("OM-%"),
                                                        MonitoringStation.code != om.TIDE_CODE,
                                                        MonitoringStation.deleted_at.is_(None))):
        d = district_of(s.area_id, areas)
        if d is None or d in ids:
            continue
        rain = pd.Series(dict(db.execute(select(RainfallObservation.observed_at, RainfallObservation.rainfall_mm).where(
            RainfallObservation.station_id == s.id, RainfallObservation.observed_at >= idx[0],
            RainfallObservation.observed_at <= idx[-1], RainfallObservation.quality_flag != "SUSPECT")).all()))
        rain = rain.reindex(idx).fillna(0.0).to_numpy(np.float32)
        X.append(features(rain, idx, ratio, s.elevation_m, s.area_id in hot, names.get(d) in TIDAL_DISTRICTS))
        ids.append(d)
    if not X:
        return {}
    p = model.predict(np.stack(X), verbose=0).ravel()
    a, b = meta["platt"]
    return {d: round(float(v), 4) for d, v in zip(ids, calibrate(p, a, b), strict=True)}
