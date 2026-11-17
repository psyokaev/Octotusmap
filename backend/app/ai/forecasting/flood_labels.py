"""Nhãn ngập giờ từ tin báo chí (historical_flood_events, không mô phỏng).

Giả định nhãn: giờ h của trạm là dương nếu quận của trạm có sự kiện bắt đầu trong [h - 1 giờ, h + 3 giờ]
(giờ bắt đầu trong tin thường gần đúng). Chỉ cửa sổ có đủ 6 giờ đích nằm trong giai đoạn đã gán nhãn
mới dùng được; ngoài giai đoạn đó nhãn là không biết, không phải "không ngập".
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

LABEL_BEFORE_H, LABEL_AFTER_H = 1, 3  # sự kiện nằm trong [h-1, h+3]


def district_of(area_id: int | None, areas: dict[int, tuple[str, int | None]]) -> int | None:
    """areas: {id: (level, parent_id)}. Phường -> quận cha."""
    if area_id is None or area_id not in areas:
        return None
    level, parent = areas[area_id]
    return parent if level == "WARD" else area_id


def hourly_labels(index: pd.DatetimeIndex, event_times: list[datetime]) -> np.ndarray:
    """1 nếu có sự kiện trong [h - 1h, h + 3h] (index: lưới giờ UTC naive)."""
    y = np.zeros(len(index), np.float32)
    for te in event_times:
        lo = index.searchsorted(pd.Timestamp(te) - timedelta(hours=LABEL_AFTER_H), "left")
        hi = index.searchsorted(pd.Timestamp(te) + timedelta(hours=LABEL_BEFORE_H), "right")
        y[lo:hi] = 1
    return y


def window_labels(hourly: np.ndarray, lookback: int, horizon: int, period: tuple[datetime, datetime], index):
    """(y[n, horizon], valid[n]) cho cửa sổ make_windows; valid = cả 6 giờ đích trong giai đoạn gán nhãn."""
    n = len(hourly) - lookback - horizon + 1
    if n <= 0:
        return np.zeros((0, horizon), np.float32), np.zeros(0, bool)
    tgt = np.arange(n)[:, None] + lookback + np.arange(horizon)
    t = index.to_numpy()[tgt]
    ok = (t >= np.datetime64(period[0])) & (t < np.datetime64(period[1]))
    return hourly[tgt], ok.all(axis=1)
