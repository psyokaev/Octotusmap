"""Tiền xử lý chuỗi thời gian cho LSTM/GRU.

Đầu vào mỗi bước giờ (FEATURES):
  rain_log   = log1p(mưa mm)                (chuẩn hoá z-score theo tập train)
  wl_rel     = (mực nước - ngưỡng ngập)     (chuẩn hoá z-score theo tập train)
  hour_sin, hour_cos (giờ địa phương)
  missing    = 1 nếu giá trị gốc thiếu và đã được điền (ffill) -> mô hình biết dữ liệu suy diễn

Đích (6 bước tới): mưa (mm), mực nước tương đối (cm), nhãn ngập (wl > ngưỡng).
Chuẩn hoá theo ngưỡng từng trạm giúp mô hình dùng chung cho mọi trạm (hỗ trợ cold-start).
"""

import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

LOOKBACK = 24
HORIZON = 6
FEATURES = ["rain_log", "wl_rel", "hour_sin", "hour_cos", "missing"]
REQUIRED_COLUMNS = {"time", "rain_mm", "water_level_cm"}


@dataclass
class Scaler:
    rain_mean: float
    rain_std: float
    wl_mean: float
    wl_std: float

    @classmethod
    def fit(cls, frames: list[pd.DataFrame]) -> "Scaler":
        rl = np.concatenate([f["rain_log"].to_numpy() for f in frames])
        wr = np.concatenate([f["wl_rel"].to_numpy() for f in frames])
        return cls(float(rl.mean()), float(rl.std() + 1e-6), float(wr.mean()), float(wr.std() + 1e-6))

    def save(self, path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Scaler":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def validate_schema(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Thiếu cột: {sorted(missing)}")
    if not df["time"].is_monotonic_increasing:
        raise ValueError("Cột time phải tăng dần")


def clean_station_frame(df: pd.DataFrame, threshold_cm: float) -> pd.DataFrame:
    """Đưa về lưới giờ đều, đánh dấu & điền giá trị thiếu (không coi là quan trắc thật)."""
    validate_schema(df)
    df = df.drop_duplicates("time").set_index("time").sort_index()
    full = pd.date_range(df.index.min(), df.index.max(), freq="h")
    df = df.reindex(full)
    rain = df["rain_mm"].astype(float)
    wl = df["water_level_cm"].astype(float)
    rain = rain.where(rain >= 0)  # âm = bất hợp lý -> thiếu
    missing = (rain.isna() | wl.isna()).astype(float)
    rain = rain.fillna(0.0)  # mưa thiếu -> 0 (giả định bảo thủ, đã gắn cờ missing)
    wl = wl.ffill().bfill()
    local_hour = (full.hour + 7) % 24
    out = pd.DataFrame({
        "rain_mm": rain.to_numpy(),
        "wl_cm": wl.to_numpy(),
        "rain_log": np.log1p(rain.to_numpy()),
        "wl_rel": (wl - threshold_cm).to_numpy(),
        "hour_sin": np.sin(2 * np.pi * local_hour / 24),
        "hour_cos": np.cos(2 * np.pi * local_hour / 24),
        "missing": missing.to_numpy(),
    }, index=full)
    out.index.name = "time"
    return out


def apply_scaler(df: pd.DataFrame, sc: Scaler) -> np.ndarray:
    x = df[FEATURES].to_numpy(dtype=np.float32).copy()
    x[:, 0] = (x[:, 0] - sc.rain_mean) / sc.rain_std
    x[:, 1] = (x[:, 1] - sc.wl_mean) / sc.wl_std
    return x


def make_windows(df: pd.DataFrame, sc: Scaler):
    """Sliding windows: X[i] = 24h quá khứ, y = 6h tới (chỉ trong cùng một đoạn thời gian)."""
    x = apply_scaler(df, sc)
    rain = df["rain_mm"].to_numpy(dtype=np.float32)
    wl_rel = df["wl_rel"].to_numpy(dtype=np.float32)
    n = len(df) - LOOKBACK - HORIZON + 1
    if n <= 0:
        empty = np.zeros((0, HORIZON), np.float32)
        return np.zeros((0, LOOKBACK, len(FEATURES)), np.float32), empty, empty, empty, []
    idx = np.arange(n)[:, None]
    X = x[idx + np.arange(LOOKBACK)]
    tgt = idx + LOOKBACK + np.arange(HORIZON)
    y_rain = rain[tgt]
    y_wl = wl_rel[tgt]
    y_flood = (y_wl > 0).astype(np.float32)
    issue_times = list(df.index[LOOKBACK - 1: LOOKBACK - 1 + n])
    return X, y_rain, y_wl, y_flood, issue_times


def chronological_split(df: pd.DataFrame, train=0.7, val=0.15):
    """Chia theo thời gian, không trộn -> tránh rò rỉ dữ liệu tương lai."""
    n = len(df)
    a, b = int(n * train), int(n * (train + val))
    return df.iloc[:a], df.iloc[a:b], df.iloc[b:]


def quality_of(missing_fraction: float, age_hours: float) -> str:
    if age_hours > 3 or missing_fraction > 0.25:
        return "POOR"
    if missing_fraction > 0.05 or age_hours > 1.5:
        return "DEGRADED"
    return "GOOD"
