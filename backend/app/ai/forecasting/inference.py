"""Suy luận dự báo 1-6h từ mô hình đang triển khai (artifact .keras + scaler)."""

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.ai.forecasting.preprocessing import HORIZON, LOOKBACK, Scaler, apply_scaler, clean_station_frame


@dataclass
class LoadedModel:
    model: object
    scaler: Scaler
    flood_threshold: float
    artifact_dir: str
    heads: tuple = ("rain", "wl", "flood")


_cache: dict[str, LoadedModel] = {}
_lock = threading.Lock()


def load(artifact_dir: str) -> LoadedModel:
    with _lock:
        if artifact_dir not in _cache:
            import keras

            d = Path(artifact_dir)
            meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
            _cache[artifact_dir] = LoadedModel(
                keras.models.load_model(d / "model.keras"), Scaler.load(d / "scaler.json"),
                float(meta.get("flood_threshold") or 0.5), artifact_dir, tuple(meta.get("heads", ("rain", "wl", "flood"))))
        return _cache[artifact_dir]


def prepare_window(df: pd.DataFrame, threshold_cm: float, sc: Scaler):
    """df: time, rain_mm, water_level_cm (UTC). Trả về (X[1,24,F], missing_fraction) hoặc None."""
    if df.empty:
        return None
    clean = clean_station_frame(df, threshold_cm)
    if len(clean) < LOOKBACK:
        return None
    tail = clean.iloc[-LOOKBACK:]
    return apply_scaler(tail, sc)[None, ...], float(tail["missing"].mean())


def predict(lm: LoadedModel, X: np.ndarray, threshold_cm) -> list[list[dict]]:
    """Dự báo theo lô; X shape (n, 24, F), threshold_cm scalar hoặc mảng n phần tử.
    Đầu ra đã đảo chuẩn hoá & ràng buộc miền giá trị (mưa >= 0, xác suất trong [0,1])."""
    out = lm.model.predict(X, verbose=0)
    out = dict(zip(lm.heads, out if len(lm.heads) > 1 else [out], strict=True))
    rain = np.clip(np.expm1(out["rain"]), 0, None)
    thr = np.broadcast_to(np.asarray(threshold_cm, dtype=float).reshape(-1, 1), (len(X), 1))
    wl_cm = out["wl"] * lm.scaler.wl_std + lm.scaler.wl_mean + thr if "wl" in out else None
    prob = np.clip(out["flood"], 0, 1) if "flood" in out else None  # None -> tính bằng chỉ số ước tính
    return [
        [{"horizon_h": h + 1, "rainfall_mm": float(round(rain[i, h], 2)),
          "water_level_cm": None if wl_cm is None else float(round(wl_cm[i, h], 1)),
          "flood_probability": None if prob is None else float(round(prob[i, h], 4))}
         for h in range(HORIZON)]
        for i in range(len(X))
    ]
